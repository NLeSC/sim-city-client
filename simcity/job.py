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

""" Manage job metadata. """

from .management import get_current_job_id, get_job_database
from couchdb.http import ResourceConflict
from .document import Job
from .util import seconds


def get_job(job_id=None, database=None):
    """
    Get a job from the job database.

    If no job_id is given, the job ID of the current process is used, if
    specified. If no database is provided, the standard job database is used.
    """
    if database is None:
        database = get_job_database()

    if job_id is None:
        job_id = get_current_job_id()
    if job_id is None:
        raise EnvironmentError("Job ID cannot be determined "
                               "(from $SIMCITY_JOBID or command-line)")
    return Job(database.get(job_id))


def queue_job(job, method, host=None, database=None):
    """
    Mark a job from the job database as being queued.

    The job is a Job object, the method a string with the type of queue being
    used, the host is the hostname that it was queued on. If no database is
    provided, the standard job database is used.
    """
    if database is None:
        database = get_job_database()

    try:
        job = database.save(job.queue(method, host))
    except ResourceConflict:
        job = get_job(job_id=job.id, database=database)
        return queue_job(job, method, host=host, database=database)
    else:
        if job['done'] > 0:
            return archive_job(job, database)
        else:
            return job


def start_job(database=None, properties=None):
    """
    Mark a job from the job database as being started.

    The job ID of the current process is used. If no database is
    provided, the standard job database is used.
    """
    if database is None:
        database = get_job_database()

    try:  # EnvironmentError if job_id cannot be determined falls through
        job = get_job()
    except ValueError:  # job ID was not yet added to database
        job = Job({'_id': get_current_job_id()})

    if properties is not None:
        for k, v in properties.items():
            job[k] = v

    try:
        return database.save(job.start())
    # Check for concurrent modification: the job may be added to the
    # database by the submission script.
    # Since this happens only once, we don't risk unlimited recursion
    except ResourceConflict:
        return start_job(database, properties=properties)


def finish_job(job, database=None):
    """
    Mark a job from the job database as being finished.

    The job is a Job object. If no database is
    provided, the standard job database is used.
    """
    if database is None:
        database = get_job_database()

    try:
        job = database.save(job.finish())
    # Check for concurrent modification: the job may be added to the
    # database by the submission script after starting.
    # Since this happens only once, we don't risk unlimited recursion
    except ResourceConflict:
        job = get_job(job_id=job.id, database=database)
        return finish_job(job, database=database)
    else:
        if job['queue'] > 0:
            return archive_job(job, database=database)
        else:
            return job


def cancel_endless_job(job, database=None):
    """
    Mark a job from the job database for cancellation.

    The job is a Job object. If no database is
    provided, the standard job database is used.
    """
    if database is None:
        database = get_job_database()

    try:
        job['cancel'] = seconds()
        return database.save(job)
    except ResourceConflict:
        job = get_job(job_id=job.id, database=database)
        return cancel_endless_job(job, database=database)


def archive_job(job, database=None):
    """
    Archive a job in the job database.

    The job is a Job object. If no database is
    provided, the standard job database is used.
    """
    if database is None:
        database = get_job_database()

    try:
        return database.save(job.archive())
    except ResourceConflict:
        job = get_job(job_id=job.id, database=database)
        return archive_job(job, database=database)
