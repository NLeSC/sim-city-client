# SIM-CITY client
#
# Copyright 2015 Joris Borgdorff <j.borgdorff@esciencecenter.nl>
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

from nose.tools import (assert_equal, assert_true, assert_not_in, assert_in,
                        assert_not_equal)
from test_mock import MockDB, MockDAV, MockRow
import simcity
from picas.util import seconds
import tempfile
import os


def test_add_task():
    simcity.management._reset_globals()
    simcity.management.set_task_database(MockDB())
    task = simcity.add_task({'key': 'my value'})
    assert_equal(task['key'], 'my value')
    assert_true(len(task.id) > 0)


def test_get_task():
    simcity.management._reset_globals()
    simcity.management.set_task_database(MockDB())
    task = simcity.get_task(MockDB.TASKS[0]['_id'])
    assert_equal(task.id, MockDB.TASKS[0]['_id'])


def test_delete_task():
    simcity.management._reset_globals()
    simcity.management._config = simcity.util.Config()
    simcity.management.set_task_database(MockDB())
    simcity.management._webdav[None] = MockDAV()
    assert_equal(0, len(simcity.management._webdav[None].removed))
    task = simcity.get_task(MockDB.TASKS[0]['_id'])
    simcity.delete_task(task)
    assert_not_in(MockDB.TASKS[0]['_id'], simcity.get_task_database().tasks)
    assert_equal(1, len(simcity.management._webdav[None].removed))


def _upload_attachment(use_dav):
    simcity.management._reset_globals()
    simcity.management.set_task_database(MockDB())
    if use_dav:
        dav = MockDAV()
        simcity.management._webdav[None] = dav

    task = simcity.get_task(MockDB.TASKS[0]['_id'])
    fd, path = tempfile.mkstemp()
    os.close(fd)
    dirname, filename = os.path.split(path)
    with open(path, 'w') as f:
        f.write('ab')

    simcity.upload_attachment(task, dirname, filename)
    os.remove(path)

    if use_dav:
        dav_path = '/' + task.id[5:7] + '/' + task.id + '/' + filename
        return (task, dirname, filename, dav, dav_path)
    else:
        return (task, dirname, filename)


def test_upload_attachment_couchdb():
    task, dirname, filename = _upload_attachment(use_dav=False)

    assert_in('_attachments', task)
    assert_in(filename, task['_attachments'])
    assert_not_in(filename, task.uploads)
    assert_in('data', task['_attachments'][filename])
    assert_equal('ab', task.get_attachment(filename)['data'])


def test_upload_attachment_webdav():
    task, dirname, filename, dav, dav_path = _upload_attachment(use_dav=True)

    assert_true('_attachments' not in task)
    assert_in(filename, task.uploads)
    assert_equal(dav.baseurl + dav_path, task.uploads[filename])
    assert_in(dav_path, dav.files)
    assert_equal('ab', dav.files[dav_path])


def test_download_attachment_webdav():
    task, dirname, filename, dav, dav_path = _upload_attachment(use_dav=True)

    path = dirname + '/' + filename
    assert_true(not os.path.exists(path))
    simcity.download_attachment(task, dirname, filename)
    assert_true(os.path.exists(path))
    with open(path, 'rb') as f:
        assert_equal('ab', f.read())
    os.remove(path)


def test_download_attachment_couchdb():
    task, dirname, filename = _upload_attachment(use_dav=False)

    path = dirname + '/' + filename
    assert_true(not os.path.exists(path))
    simcity.download_attachment(task, dirname, filename)
    assert_true(os.path.exists(path))
    with open(path, 'rb') as f:
        assert_equal('ab', f.read())
    os.remove(path)


def test_delete_attachment_webdav():
    task, dirname, filename, dav, dav_path = _upload_attachment(use_dav=True)

    assert_in(dav_path, dav.files)
    assert_in(filename, task.uploads)
    simcity.delete_attachment(task, filename)
    assert_not_in(dav_path, dav.files)
    assert_not_in(filename, task.uploads)


def test_delete_attachment_couchdb():
    task, dirname, filename = _upload_attachment(use_dav=False)

    assert_in(filename, task['_attachments'])
    simcity.delete_attachment(task, filename)
    assert_not_in(filename, task['_attachments'])


def _get_task():
    simcity.management._reset_globals()
    db = MockDB()
    simcity.management.set_task_database(db)
    return (db, simcity.get_task(MockDB.TASKS[0]['_id']))


def test_scrub_task():
    db, task = _get_task()
    assert_equal(0, task['lock'])
    task.lock()
    assert_not_equal(0, task['lock'])
    db.tasks[task.id]['_rev'] = 'myrev'
    db.tasks[task.id]['lock'] = task['lock']
    db.viewList = [MockRow(task.id, task.value, task.id)]
    assert_equal(0, len(db.saved))

    simcity.scrub_tasks('locked', age=0)
    assert_equal(1, len(db.saved))
    task_id, task = db.saved.popitem()
    assert_equal(0, task['lock'])


def test_scrub_old_task_none():
    db, task = _get_task()
    task.lock()
    assert_equal(0, len(db.saved))
    db.viewList = [MockRow(task.id, task.value, task.id)]
    simcity.scrub_tasks('locked', age=2)
    assert_equal(0, len(db.saved))


def test_scrub_old_task():
    db, task = _get_task()
    task['lock'] = seconds() - 100
    assert_not_equal(0, task['lock'])
    db.tasks[task.id]['_rev'] = 'myrev'
    db.tasks[task.id]['lock'] = task['lock']
    db.viewList = [MockRow(task.id, task.value, task.id)]
    assert_equal(0, len(db.saved))

    simcity.scrub_tasks('locked', age=2)
    assert_equal(1, len(db.saved))
    old_task_id = task.id
    task_id, task = db.saved.popitem()
    assert_equal(task_id, old_task_id)
    assert_equal(0, task['lock'])
