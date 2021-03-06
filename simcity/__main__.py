# SIM-CITY client
#
# Copyright 2015 Netherlands eScience Center
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
SIM-CITY scripts
"""

from __future__ import print_function
import simcity
from simcity import (PrioritizedViewIterator, TaskViewIterator,
                     EndlessViewIterator, Config, FileConfig,
                     load_config_database, submit_while_needed)
from .util import seconds_to_str, sizeof_fmt
import argparse
import getpass
import couchdb
import sys
import json
import signal
import traceback
import yaml
from tqdm import tqdm
import os
from uuid import uuid4

task_views = frozenset(['pending', 'done', 'in_progress', 'error'])
job_views = frozenset(['pending_jobs', 'running_jobs', 'finished_jobs',
                       'archived_jobs', 'active_jobs'])


def fill_argument_parser(parser):
    """ Fill an argparse.ArgumentParser with arguments and subparsers. """
    global task_views, job_views

    parser.add_argument(
        '-c', '--config', help="configuration file")
    parser.add_argument('-v', '--version', action='version',
                        version='%(prog)s {0}\\nPython version {1}'
                        .format(simcity.__version__, sys.version))

    subparsers = parser.add_subparsers()

    cancel_parser = subparsers.add_parser('cancel', help="Cancel running job")
    cancel_parser.add_argument('job_id', help="JOB ID to cancel")
    cancel_parser.set_defaults(func=cancel)

    check_parser = subparsers.add_parser(
        'check', help="check the status of all running and pending jobs")
    check_parser.add_argument(
        '-n', '--dry-run', action='store_true',
        help="Only show what status would be modified, do not modify.")
    check_parser.add_argument(
        '-m', '--max', type=int, default=2,
        help='maximum jobs to run to process tasks')
    check_parser.add_argument(
        'host', nargs='?', help='host to submit additional jobs to, if needed')
    check_parser.set_defaults(func=check)

    create_parser = subparsers.add_parser(
        'create', help="Create new tasks in the database")
    create_parser.add_argument('command', help="command to run")
    create_parser.add_argument('arguments', nargs='*', help="arguments")
    create_parser.add_argument(
        '-n', '--number', type=int, default=1,
        help="number of tasks to create (default: %(default)s)")
    create_parser.add_argument(
        '-p', '--parallelism', default=1,
        help="number of threads the task needs. Use '*' for as many as "
             "available. (default: %(default)s)", )
    create_parser.add_argument(
        '-i', '--input', help="input json file")
    create_parser.set_defaults(func=create)

    delete_parser = subparsers.add_parser(
        'delete', help="Remove all documents in a view")
    delete_group = delete_parser.add_mutually_exclusive_group(required=True)
    delete_group.add_argument(
        '-v', '--view',
        help="View to remove documents from (usually one of {0})"
             .format(task_views | job_views))
    delete_group.add_argument('id', nargs='?', help="document ID")
    delete_parser.add_argument(
        '-d', '--design', help="design document in CouchDB", default='Monitor')
    delete_parser.set_defaults(func=delete)

    get_parser = subparsers.add_parser('get', help='get document')
    get_parser.add_argument('id', help='document ID')
    get_parser.add_argument('-d', '--download',
                            help='download task to directory')
    get_parser.set_defaults(func=get)

    init_parser = subparsers.add_parser(
        'init', help="Initialize the SIM-CITY databases and views as "
                     "configured.")
    init_parser.add_argument(
        '-p', '--password', help="admin password")
    init_parser.add_argument(
        '-v', '--view', action='store_true',
        help="ONLY set the database views")
    init_parser.add_argument(
        '-u', '--user', help="admin user")
    init_parser.set_defaults(func=init)

    list_parser = subparsers.add_parser('list', help='list documents')
    list_parser.add_argument('view', help='view name',
                             choices=task_views | job_views)
    list_parser.add_argument('-l', '--limit', default=0, type=int,
                             help='maximum number of items to show '
                                  '(default: %(default))')
    list_parser.add_argument('-o', '--offset', default=0,
                             help='offset to show items from')
    list_parser.set_defaults(func=list_documents)

    run_parser = subparsers.add_parser('run', help="Execute tasks")
    run_parser.add_argument('-D', '--days', type=int, default=1,
                            help="number of days to execute tasks "
                                 "(default: %(default)s)")
    run_parser.add_argument('-H', '--hours', type=int, default=0,
                            help="number of hours to execute tasks "
                                 "(default: %(default)s)")
    run_parser.add_argument('-M', '--minutes', type=int, default=0,
                            help="number of minutes to execute task s"
                                 "(default: %(default)s)")
    run_parser.add_argument('-S', '--seconds', type=int, default=0,
                            help="number of seconds to execute tasks "
                                 "(default: %(default)s)")
    run_parser.add_argument('-m', '--margin', type=float, default=1.5,
                            help="margin factor for average task time in "
                                 "calculating maximum time (default: "
                                 "%(default)s)")
    run_parser.add_argument('-l', '--local', action='store_true',
                            help="run locally without a job_id")
    run_parser.add_argument('-p', '--parallelism', default='*',
                            help="number of parallel processes to use for the "
                                 "computation. Use '*' for all cpu cores. "
                                 "(default: %(default)s)")
    run_parser.add_argument('-e', '--endless', action="store_true",
                            help="run until cancelled, even if no "
                                 "new jobs arrive.")
    run_parser.add_argument('-P', '--prioritize', action="store_true",
                            help="prioritize tasks")
    run_parser.add_argument('job_id', nargs='?', help="JOB ID to assume")
    run_parser.set_defaults(func=run)

    scrub_parser = subparsers.add_parser(
        'scrub',
        help="Make old in progress tasks available for processing again")
    scrub_task_views = task_views - frozenset(['done'])
    scrub_job_views = job_views - frozenset(['archived_jobs'])
    scrub_parser.add_argument('-D', '--days', type=int, default=0,
                              help="number of days ago the task was in "
                                   "progress (default: %(default)s)")
    scrub_parser.add_argument('-H', '--hours', type=int, default=0,
                              help="number of hours ago the task was in "
                                   "progress (default: %(default)s)")
    scrub_parser.add_argument('-M', '--minutes', type=int, default=0,
                              help="number of minutes ago the task was in "
                                   "progress (default: %(default)s)")
    scrub_parser.add_argument('-S', '--seconds', type=int, default=0,
                              help="number of seconds ago the task was in "
                                   "progress (default: %(default)s)")
    scrub_parser.add_argument('view', default='in_progress',
                              help="view to scrub (default: %(default)s)",
                              choices=scrub_task_views | scrub_job_views)
    scrub_parser.set_defaults(func=scrub)

    summary_parser = subparsers.add_parser(
        'summary', help="Summary of the infrastructure")
    summary_parser.set_defaults(func=summary)

    submit_parser = subparsers.add_parser('submit', help="Start a job")
    submit_parser.add_argument('host', help="host to run pilot job on")
    submit_parser.add_argument(
        '-m', '--max', type=int, default=2,
        help="only run if there are less than MAX jobs running "
             "(default: %(default)s)")
    submit_parser.add_argument(
        '-f', '--force', action='store_true',
        help="also start if there are more that MAX jobs running")
    submit_parser.set_defaults(func=submit)


def main():
    """ Parse all arguments of the simcity script. """
    parser = argparse.ArgumentParser(prog='simcity',
                                     description='SIM-CITY scripts')
    fill_argument_parser(parser)

    args = parser.parse_args()
    if 'func' not in args:
        parser.print_help()
        sys.exit(1)

    if args.func != init:
        try:
            simcity.init(config=args.config)
        except couchdb.http.ResourceNotFound:
            print('Configuration does not correctly specify the databases.')
            sys.exit(1)

    args.func(args)


def cancel(args):
    """ Cancel running job. """
    job = simcity.get_job(args.job_id)
    simcity.cancel_endless_job(job)


def create(args):
    """
    Create tasks with a single command
    """
    # Load the tasks to the database
    for i in range(args.number):
        try:
            task = {
                'command': args.command,
                'arguments': args.arguments,
                'parallelism': args.parallelism,
            }
            try:
                with open(args.input) as f:
                    task['input'] = json.load(f)
            except TypeError:
                pass

            task = simcity.add_task(task)

            print("added task {0}".format(task.id))
        except Exception as ex:
            print("ERROR: task {0} failed to be added: {1}".format(i, ex),
                  file=sys.stderr)


def delete(args):
    """ Delete documents """
    if args.id is not None:
        try:
            db = simcity.get_task_database()
            db.delete(db.get(args.id))
        except ValueError:
            try:
                db = simcity.get_job_database()
                db.delete(db.get(args.id))
            except ValueError:
                print("Cannot find document ID {0}".format(args.id))
                sys.exit(1)

    if args.view is not None:
        if args.view in job_views:
            db = simcity.get_job_database()
        else:
            db = simcity.get_task_database()

        is_deleted = db.delete_from_view(args.view, design_doc=args.design)
        print("Deleted %d out of %d tasks from view %s" %
              (sum(is_deleted), len(is_deleted), args.view))


def get(args):
    """ Get document and print it """
    if args.download is not None:
        if not os.path.isdir(args.download):
            os.makedirs(args.download)
    try:
        doc = simcity.get_task(args.id)
        doc['lock_str'] = seconds_to_str(doc['lock'], 'not started')
        doc['done_str'] = seconds_to_str(doc['done'], 'not done')
        if args.download is not None:
            lengths = {}
            for filename in doc.list_files():
                try:
                    lengths[filename] = doc.files[filename]['length']
                except KeyError:
                    lengths[filename] = doc['_attachments'][filename]['length']
            total_length = sum(lengths.values())

            print('Downloading {0} to {1}'
                  .format(sizeof_fmt(total_length), args.download))
            pbar = tqdm(total=total_length, unit_scale=True, unit='B')
            for filename in doc.list_files():
                simcity.download_attachment(doc, args.download, filename)
                pbar.update(lengths[filename])
            pbar.close()
    except (ValueError, KeyError):
        try:
            doc = simcity.get_job(args.id)
            doc['queue_str'] = seconds_to_str(doc['queue'], 'not queued')
            doc['start_str'] = seconds_to_str(doc['start'], 'not started')
            doc['done_str'] = seconds_to_str(doc['done'], 'not done')
        except (ValueError, KeyError):
            print("Document {0} not found".format(args.id))
            sys.exit(1)

    if args.download is None:
        print(yaml.safe_dump(dict(doc), default_flow_style=False))
    else:
        with open(os.path.join(args.download, '_document.json'), 'w') as f:
            json.dump(dict(doc), f)


def init(args):
    """
    Create the databases and views
    """
    if args.user is not None and args.password is None:
        try:
            args.password = getpass.getpass('Password:')
        except KeyboardInterrupt:  # cancel password prompt
            print("")
            sys.exit(1)

    if args.view:
        config = Config()
        config.configurators.append(FileConfig(args.config))
        try:
            config.configurators.append(load_config_database(config))
        except KeyError:
            pass

        if args.user is not None:
            config.add_section('task-db', {
                'username': args.user,
                'password': args.password,
            })
            if 'job-db' in config.sections():
                config.add_section('job-db', {
                    'username': args.user,
                    'password': args.password,
                })
        try:
            simcity.init(config)
            simcity.create_views()
        except couchdb.http.ResourceNotFound:
            print("Database not initialized, run `simcity init` without -v "
                  "flag.")
            sys.exit(1)
        except couchdb.http.Unauthorized:
            print("CouchDB user and/or password incorrect")
            sys.exit(1)
    else:
        try:
            simcity.init(config=args.config)
        except couchdb.http.ResourceNotFound:
            pass  # database does not exist yet
        except couchdb.http.Unauthorized:
            pass  # user does not exist yet

        try:
            simcity.create(args.user, args.password)
        except couchdb.http.Unauthorized:
            print("User and/or password incorrect")
            sys.exit(1)


def list_documents(args):
    """ List documents in a view. """
    global task_views

    options = {}
    if args.limit > 0:
        options['limit'] = args.limit
    if args.offset > 0:
        options['skip'] = args.offset

    if args.view in task_views:
        view = simcity.get_task_database().view(args.view, **options)
        if args.view == 'error':
            for row in view:
                print('{0}:'.format(row.id))
                for error in row.value:
                    print('  - time: {0}'
                          .format(seconds_to_str(error['time'])))
                    if 'message' in error:
                        print('    message: {0}'
                              .format(error['message']))
                    if 'exception' in error:
                        exception_str = '\n    '.join(
                            error['exception'].splitlines())
                        print('    exception:\n'
                              '    ==========\n'
                              '    {0}=========='
                              .format(exception_str))
        else:
            print('{:<40} {:<22} {:<22}'.format('ID', 'started', 'stopped'))
            print('-' * (40 + 1 + 22 + 1 + 22))
            for row in view:
                lock = seconds_to_str(row.value['lock'], 'not started')
                done = seconds_to_str(row.value['done'], 'not done')
                print('{:<40} {:<22} {:<22}'.format(row.id[:40], lock, done))
    else:
        view = simcity.get_job_database().view(args.view, **options)
        print('{:<45} {:<22} {:<22} {:<22}'.format('ID', 'queued', 'started',
                                                   'stopped'))
        print('-' * (45 + 1 + 22 + 1 + 22 + 1 + 22))
        for row in view:
            queued = seconds_to_str(row.value['queue'], 'not queued')
            start = seconds_to_str(row.value['start'], 'not started')
            done = seconds_to_str(row.value['done'], 'not done')
            print('{:<45} {:<22} {:<22} {:<22}'.format(row.id[:45], queued,
                                                       start, done))


def _is_cancelled():
    """ Whether the job was cancelled """
    db = simcity.get_job_database()
    try:
        job_id = simcity.get_current_job_id()
        return db.get(job_id)['cancel'] > 0
    except KeyError:
        return False


def _signal_handler(signal, frame):
    """ Catch signals to do a proper cleanup.
        The job then has time to write out any results or errors. """
    print('Caught signal %d; finishing job.' % signal, file=sys.stderr)
    try:
        simcity.finish_job(simcity.get_job())
    except Exception as ex:
        print('Failed during clean-up: {0}'.format(ex))

    sys.exit(1)


def _time_args_to_seconds(args):
    """
    Convert an object with days, hours, minutes and seconds properties
    to a single seconds int.
    """
    hours = args.hours + (24 * args.days)
    return args.seconds + 60 * (args.minutes + 60 * hours)


def run(args):
    """ Run job to process tasks. """
    if args.job_id is not None:
        simcity.set_current_job_id(args.job_id)
    elif args.local:
        simcity.set_current_job_id('local-' + uuid4().hex)

    job_id = simcity.get_current_job_id()

    db = simcity.get_task_database()

    if args.prioritize:
        iterator = PrioritizedViewIterator(job_id, db, 'pending_priority',
                                           'pending')
    else:
        iterator = TaskViewIterator(job_id, db, 'pending')

    if args.endless:
        iterator = EndlessViewIterator(job_id, iterator,
                                       stop_callback=_is_cancelled)

    actor = simcity.JobActor(iterator, simcity.ExecuteWorker)

    for sig_name in ['HUP', 'INT', 'QUIT', 'ABRT', 'TERM']:
        try:
            sig = signal.__dict__['SIG%s' % sig_name]
        except Exception as ex:
            print(ex, file=sys.stderr)
        else:
            signal.signal(sig, _signal_handler)

    # Start work!
    print("Connected to the database successfully. Now starting work...")
    try:
        actor.run(maxtime=_time_args_to_seconds(args),
                  avg_time_factor=args.margin)
    except Exception as ex:
        print("Error occurred: %s: %s" % (str(type(ex)), str(ex)),
              file=sys.stderr)
        traceback.print_exc(file=sys.stderr)

    print("No more tasks to process, done.")


def scrub(args):
    """
    Scrub tasks or jobs in a given view to return to their previous status.
    """
    age = _time_args_to_seconds(args)

    scrubbed, total = simcity.scrub(args.view, age=age)

    if scrubbed > 0:
        print("Scrubbed %d out of %d documents from '%s'" %
              (scrubbed, total, args.view))
    else:
        print("No scrubbing required")


def submit(args):
    """ Submit job to the infrastructure """
    if args.force:
        job = simcity.submit(args.host)
    else:
        job = simcity.submit_if_needed(args.host, args.max)
    if job is None:
        print("No tasks to process or already %d jobs running (increase "
              "maximum number of jobs with -m)" % args.max)
    else:
        print("Job %s (ID: %s) started" % (job['batch_id'], job.id))


def summary(args):
    """ Print summary of tasks. """
    print('Summary')
    print(20 * '=')
    overview = simcity.overview_total()
    for k in sorted(overview.keys()):
        print('{0:<15} {1}'.format(k, overview[k]))
    print(20 * '=')


def check(args):
    """
    Checks the consistency of the database

    1. active_jobs that are no longer in the queue can be archived
    2. tasks registered with jobs that are no longer running can be cancelled
    3. if there are tasks pending with not enough running_jobs or pending_jobs
       a new job can be started.

    run `simcity check` in cron.
    """
    if args.dry_run:
        print("Dry run: will not modify any state")

    print('BEFORE: ', end='')
    summary(args)

    # check job status
    jobs = simcity.check_job_status(dry_run=args.dry_run)
    for job in jobs:
        if job['archive'] > 0:
            print("Archiving stopped job {}".format(job.id))

    tasks = simcity.check_task_status(dry_run=args.dry_run)
    for task in tasks:
        print("Marking task {} that ran in job {} as error"
              .format(task.id, task['job']))
        task.error('Failed to finish task in time, the job has stopped '
                   'already.')
        simcity.get_task_database().save(task)

    if args.host is None:
        print("No host provided, not starting additional jobs")
    else:
        jobs = submit_while_needed(args.host, args.max, dry_run=args.dry_run)
        if len(jobs) == 0:
            print("Enough jobs running. Will not start any new jobs")
        else:
            if args.dry_run:
                print("Would start {} jobs".format(len(jobs)))
            else:
                for job in jobs:
                    print("Job {0} (ID: {1}) started"
                          .format(job['batch_id'], job.id))

    print('AFTER: ', end='')
    summary(args)
