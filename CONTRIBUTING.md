# How to contribute

## How to prepare

* You need a [GitHub account](https://github.com/signup/free)
* Submit an [issue ticket](https://github.com/tomato42/tlslite-ng/issues) for
  your issue if there is none yet.
  * Describe the issue and include steps to reproduce if it's a bug, mention
    the earliest version that you know is affected and the version you're using.
  * Describe the enhancement and your general ideas on how to implement it
    if you want to add new feature or extend existing one. This is not
    necessary if the change is small.
* If you are able and want to fix the issue, fork the repository on GitHub

## Technical requirements

To be able to work on the code you will need few pieces of software installed.
The most important is `python` interpreter. Some development dependencies have
additional restrictions on the versions used, so I recommend Python 2.7 or
Python 3.4 as the lowest versions. Git client, make, text editor and ability to
install local python packages (ability to run pip).

The list goes as follows:
 * python (2.7 or 3.4)
 * git
 * GNU make
 * pip

The python module dependencies are as follows:
 * ecdsa
 * pylint
 * diff_cover
 * coverage
 * hypothesis

On Fedora they can be installed using:
```
dnf install python-ecdsa python3-ecdsa pylint python3-pylint python-diff-cover \
    python3-diff-cover python-coverage python3-coverage python2-hypothesis \
    python3-hypothesis
```

Optional module dependencies:
 * tackpy
 * m2crypto
 * pycrypto
 * gmpy

On Fedora they can be installed using:
```
pip install tackpy
dnf install m2crypto python-crypto python3-crypto python-gmpy2 python3-gmpy2
```

## Make changes

* In your forked repository, create a topic branch for your upcoming patch
  (e.g. 'implement-aria' or 'bugfix-osx-crash')
  * usually this is based on the master branch
  * to create branch based on master: `git branch <example-name>` then
    checkout the branch `git checkout <example-name>`. For your own convinience
    avoid working directly on the `master` branch.
* Make sure you stick to the coding style that is used in surrounding code
  * you can use `pylint --msg-template="{path}:{line}: [{msg_id}({symbol}),
    {obj}] {msg}" tlslite > pylint_report.txt; diff-quality --violations=pylint
    pylint_report.txt` to see if your changes do not violate the general
    guidelines (alternatively you can just run `make test-dev` as described
    below).
* Make commits of logical units and describe them properly in commits
  * When creating a comment, keep the first line short and separate it from
    the rest by whiteline
* Check for unnecessary whitespace with `git diff --check` before committing

* Generally newly submitted code should have test coverage so that it can
  be clearly shown that it works correctly.
  * pull requests with code refactoring of code that does not have test
    coverage should have test coverage of the code added first
* Assure nothing is broken by running all tests using `make test-dev`
  * Pull requests that fail the last check of the `test-dev` target,
    the test coverage check, may still be accepted, but making pull request
    that passes it is the best way to make the review quick.

## Submit changes
* Push your changes to a topic branch in your fork of the repository.
* Open a pull request to the original repository and choose the right original
  branch you want to patch (that usually will be tomato42/master).
* If you posted issues previously, make sure you reference them in the opening
  commit of the pull request (e.g. 'fixes #12'). But _please do not close the
  issue yourself_. GitHub will do that automatically once the issue is merged.
* Wait for checks to pass. Travis-ci check is mandatory, pull requests which
  fail it will not be merged. Landscape and coveralls failures are not blocking
  but may require explanation. Going to codeclimate and quantified code
  (see README.md for links) and checking the branch and pull request is also
  a good idea.
  * if you are not sure if the pull will pass the checks it is OK to submit
    a test pull request, but please mark it as such ('[WIP]' in title is
    enough)

# Additional Resources

* [General GitHub documentation](http://help.github.com/)
* [GitHub pull request documentation](http://help.github.com/send-pull-requests/)
