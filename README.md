# Run a simulation on SIM-CITY infrastructure

SIM-CITY client 0.2. Uses a pilot job script to run multiple simulations in the same job.

## Dependencies

The best way to manage this package is through the Python `virtualenv` package. On a cluster resource run the following commands:

    module load python/2.7
    pip install --user virtualenv
    ~/.local/bin/virtualenv simcity

Then before every run or installation, include the `simcity` virtualenv:

    module load python/2.7
    . simcity/bin/activate

## Installation

Simply run

    make install

Copy the `config.ini.dist` file to `config.ini` or to `~/.simcity_client`. Set the correct values for the CouchDB database and if you intend to run jobs on this location also set the executable settings. There are two CouchDB database sections, one for the jobs and one for the tasks. If these are the same, you can remove the jobs database section.

## Usage

**Run a script** on a cluster:

    $ python scripts/submitJob.py 'path/to/job/on/cluster' cluster

The cluster can be configured in the config.ini file, as a section [$CLUSTER_NAME-host].

**Load tasks** to your database: 

	$ python scripts/createTasks.py COMMAND TOKEN_ID

The TOKEN_ID must be unique. Refresh the database to see the tasks.

**Create basic views** (todo, locked, done, error, overview):

	$ python scripts/createViews.py

Refresh the database to see the views. Unfold top right tab 'View:All documents' to inspect each view.

**Run a simple example** that calculates the square of a set of tasks:
   
	$ python scripts/runExample.py

This will run an executable on your local machine. To submit the same on a cluster, you need to add the 'python runExample.py' command for example in a shell script and submit this with qsub. See for example `scripts/lisaSubmitExpress.sh`.

## Contributing

We use git-flow for managing branches. To add a feature, first run

    make test

and then commit, to make sure the change didn't break any code.
