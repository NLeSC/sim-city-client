import simcity
import simcity.job
from simcity.util import listfiles, write_json, Timer, expandfilename
from simcity.task.iterator import TaskViewIterator

import os
from subprocess import call

class RunActor(object):
    """Executor class to be overwritten in the client implementation.
    """
    def __init__(self, task_db):
        """
        @param database: the database to get the tasks from.
        @param job_id: job id.
        """
        if task_db is None:
            raise ValueError("Database must be initialized")
        
        self.task_db = task_db

    def run(self, maxtime=-1):
        """Run method of the actor, executes the application code by iterating
        over the available tasks in CouchDB.
        """
        job = simcity.job.start()
        
        time = Timer()
        self.prepare_env()
        for task in TaskViewIterator('todo', database=self.task_db):
            self.prepare_run()
            
            try:
                self.process_task(task)
            except Exception as ex:
                msg = "Exception " + str(type(ex)) + " occurred during processing: " + str(ex)
                task.error(msg, exception=ex)
                print msg
            
            self.task_db.save(task)
            self.cleanup_run()
            
            if maxtime > 0 and time.elapsed() > maxtime:
                break
        
        self.cleanup_env()
        
        simcity.job.finish(job)
        
    def prepare_env(self, *kargs, **kwargs):
        """Method to be called to prepare the environment to run the 
        application.
        """
        pass
    
    def prepare_run(self, *kargs, **kwargs):
        """Code to run before a task gets processed. Used e.g. for fetching
        inputs.
        """
        pass
    
    def process_task(self, task):
        """The function to overwrite which processes the tasks themselves.
        @param key: the task key. Should not be used to hold anything
        informative as it is mainly used to determine the order in which the
        tasks are returned.
        @param key: the key indicating where the task is stored in the 
        database.
        @param task: the task itself. !WARNING
        """
        raise NotImplementedError

    def cleanup_run(self, *kargs, **kwargs):
        """Code to run after a task has been processed.
        """
        pass
    
    def cleanup_env(self, *kargs, **kwargs):
        """Method which gets called after the run method has completed.
        """
        pass

class ExecuteActor(RunActor):
    def __init__(self, task_db = None, config = None):
        if task_db is None:
            task_db = simcity.task.database
        super(ExecuteActor, self).__init__(task_db)
        if config is None:
            config = simcity.config
        self.config = config.section('Execution')
    
    def process_task(self, task):
        print "-----------------------"
        print "Working on task: " + task.id

        dirs = self.create_dirs(task)
        params_file = os.path.join(dirs['input'], 'input.json')
        write_json(params_file, task.input)
        
        task['execute_properties'] = {'dirs': dirs, 'input_file': params_file}
        
        command = [expandfilename(task['command']), dirs['tmp'], dirs['input'], dirs['output']]
        stdout = os.path.join(dirs['output'], 'stdout')
        stderr = os.path.join(dirs['output'], 'stderr')
        try:
            with open(stdout, 'w') as fout, open(stderr, 'w') as ferr:
                returnValue = call(command,stdout=fout, stderr=ferr)
            
            if returnValue != 0:
                task.error("Command failed")
        except Exception as ex:
            task.error("Command raised exception", ex)
        
        task.output = {}
        
        # Read all files in as attachments
        out_files = listfiles(dirs['output'])
        for filename in out_files:
            with open(os.path.join(dirs['output'], filename), 'r') as f:
                task.put_attachment(filename, f.read())

        task.done()
        print "-----------------------"
    
    def create_dirs(self, task):
        dir_map = {'tmp': 'tmp_dir', 'input': 'input_dir', 'output': 'output_dir'}
        
        dirs = {}
        for d, conf in dir_map.iteritems():
            superdir = expandfilename(self.config[conf])
            try:
                os.mkdir(superdir)
            except OSError: # directory exists
                pass
            
            dirs[d] = os.path.join(superdir, task.id + '_' + str(task['lock']))
            os.mkdir(dirs[d])
        
        return dirs