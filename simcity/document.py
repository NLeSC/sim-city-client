# SIM-CITY client
#
# Copyright 2015 Netherlands eScience Center, Jan Bot
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
# limitations under the License."""

"""
CouchDB document types.
"""
import socket
from .util import merge_dicts, seconds
import mimetypes
import base64
import traceback
from uuid import uuid4


class Document(object):
    """ A CouchDB document """

    def __init__(self, data={}, base={}):
        if isinstance(data, Document):
            data = data.value

        # Data is not from the database
        if '_rev' not in data:
            data = merge_dicts(base, data)

        self.doc = data

    # Python Dict emulation:
    # docs.python.org/2/reference/datamodel.html#emulating-container-types
    def __len__(self):
        return self.doc.__len__()

    def __getitem__(self, idx):
        return self.doc.__getitem__(idx)

    def __setitem__(self, idx, value):
        return self.doc.__setitem__(idx, value)

    def __delitem__(self, idx):
        return self.doc.__delitem__(idx)

    def __contains__(self, idx):
        return self.doc.__contains__(idx)

    def __iter__(self):
        return self.doc.__iter__()
    # End python dict emulation

    @property
    def id(self):
        """ Document ID (_id)"""
        try:
            return self.doc['_id']
        except KeyError:
            raise AttributeError("_id for document is not set")

    @property
    def rev(self):
        """ Document revision (_rev) """
        try:
            return self.doc['_rev']
        except KeyError:
            raise AttributeError("_rev is not available: document is not "
                                 "retrieved from database")

    @id.setter
    def id(self, new_id):
        self.doc['_id'] = new_id

    @property
    def value(self):
        """ Document raw dict value """
        return self.doc

    def update(self, values):
        """Add the output of the RunActor to the task.
        """
        self.doc.update(values)

    @property
    def attachments(self):
        return self.doc.setdefault('_attachments', {})

    def put_attachment(self, name, data, mimetype=None):
        """
        Put an attachment in the document.

        The attachment data must be provided as str in Python 2 and bytes in
        Python 3.

        The mimetype, if not provided, is guessed from the filename and
        defaults to text/plain.
        """
        if mimetype is None:
            mimetype, encoding = mimetypes.guess_type(name)
            if mimetype is None:
                mimetype = 'text/plain'

        b64data = base64.b64encode(data)
        self.attachments[name] = {
            'content_type': mimetype, 'data': b64data}

    def get_attachment(self, name, retrieve_from_database=None):
        """ Gets an attachment dict from the document.
        Attachment data may not have been copied over from the
        database, in that case it will have an md5 checksum.
        A CouchDB database may be set in retrieve_from_database to retrieve
        the data if it is not present.

        The attachment data will be returned as str in Python 2 and bytes in
        Python 3.

        Raises KeyError if attachment does not exist.
        """
        # Copy all attributes except data, it may be very large
        attachment = {}
        for key in self.attachments[name]:
            if key != 'data':
                attachment[key] = self.attachments[name][key]

        if 'data' in self.attachments[name]:
            attachment['data'] = base64.b64decode(
                self.attachments[name]['data'])
        elif retrieve_from_database is not None:
            db = retrieve_from_database.db
            f_attach = db.get_attachment(self.id, name)
            try:
                attachment['data'] = f_attach.read()
            finally:
                f_attach.close()

            b64data = base64.b64encode(attachment['data'])
            self.attachments[name]['data'] = b64data

        return attachment

    def delete_attachment(self, name):
        """ Deletes attachment from document
        @param name: document name
        @raise KeyError: if document name does not exist
        """
        del self.attachments[name]
        return self

    def _update_hostname(self):
        """ Update the hostname value to the current host. """
        self.doc['hostname'] = socket.gethostname()
        return self

    def list_files(self):
        """ All attachment names associated to a task. """
        return list(self.attachments.keys())


class User(Document):
    """ CouchDB user """
    def __init__(self, username, password, roles=[], data={}):
        super(User, self).__init__(
            data=data,
            base={
                '_id': 'org.couchdb.user:{0}'.format(username),
                'name': username,
                'type': 'user',
                'password': password,
                'roles': roles,
            })


class Task(Document):
    """ Class to manage task modifications with. """

    __BASE = {
        'type': 'task',
        'lock': 0,
        'done': 0,
        'hostname': '',
        'scrub_count': 0,
        'input': {},
        'output': {},
        'uploads': {},
        'error': [],
    }

    def __init__(self, task={}):
        super(Task, self).__init__(task, Task.__BASE)
        if '_id' not in self.doc:
            self.doc['_id'] = 'task_' + uuid4().hex

    def lock(self):
        """Function which modifies the task such that it is locked.
        """
        self.doc['lock'] = seconds()
        return self._update_hostname()

    def done(self):
        """Function which modifies the task such that it is closed for ever
        to the view that has supplied it.
        """
        self.doc['done'] = seconds()
        return self

    @property
    def input(self):
        """ Get input """
        return self.doc['input']

    @input.setter
    def input(self, value):
        """ Set input """
        self.doc['input'] = value

    @property
    def output(self):
        """Get the output from the RunActor."""
        return self.doc['output']

    @output.setter
    def output(self, output):
        """Add the output of the RunActor to the task.
        """
        self.doc['output'] = output

    @property
    def uploads(self):
        """ Associated files that were uploaded. """
        return self.doc.setdefault('uploads', {})

    @uploads.setter
    def uploads(self, uploads):
        self.doc['uploads'] = uploads

    def list_files(self):
        """ All attachment names associated to a task. """
        return list(self.uploads.keys()) + list(self.attachments.keys())

    def scrub(self):
        """
        Task scrubber: makes sure a task can be handed out again if it was
        locked more than t seconds ago.
        """
        if 'scrub_count' not in self.doc:
            self.doc['scrub_count'] = 0
        self.doc['scrub_count'] += 1
        self.doc['done'] = 0
        self.doc['lock'] = 0
        return self._update_hostname()

    def error(self, msg=None, exception=None):
        """ Set an error for the task. """
        error = {'time': seconds()}
        if msg is not None:
            error['message'] = str(msg)

        if exception is not None:
            error['exception'] = traceback.format_exc()

        self.doc['lock'] = -1
        self.doc['done'] = -1
        if 'error' not in self.doc:
            self.doc['error'] = []
        self.doc['error'].append(error)
        return self

    def has_error(self):
        """ Whether the task had an error. """
        return self.doc['lock'] == -1

    def get_errors(self):
        """ Get the list of errors. """
        try:
            return self.doc['error']
        except KeyError:
            return []

    def is_done(self):
        """ Whether the task successfully finished. """
        return self.doc['done'] != 0


class Job(Document):
    """ Class to manage a CouchDB job entry. """
    __BASE = {
        'type': 'job',
        'hostname': '',
        'start': 0,
        'done': 0,
        'queue': 0,
        'method': '',
        'archive': 0,
    }

    def __init__(self, job):
        super(Job, self).__init__(job, Job.__BASE)
        if '_id' not in self.doc:
            raise ValueError('Job ID must be set')

    def queue(self, method, host=None):
        """ Save that the job was queued. """
        self.doc['method'] = method
        if host is not None:
            self.doc['hostname'] = host
        self.doc['queue'] = seconds()
        return self

    def start(self):
        """ Save that the job has started. """
        self.doc['start'] = seconds()
        self.doc['done'] = 0
        self.doc['archive'] = 0
        return self._update_hostname()

    def finish(self):
        """ Save that the job is done. """
        self.doc['done'] = seconds()
        return self

    def archive(self):
        """ Move the job to an archived state. """
        if self.doc['done'] <= 0:
            self.doc['done'] = seconds()
        self.doc['archive'] = seconds()
        self.id = 'archived-' + self.id + '-' + str(seconds())
        del self.doc['_rev']
        return self

    def is_done(self):
        """ Whether the job is done. """
        return self.doc['done'] != 0
