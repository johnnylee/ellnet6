#!/usr/bin/env python

from distutils.core import setup

setup(name             = "ellnet",
      version          = "0.1",
      description      = "IPv6 link-local networking.",
      author           = "J. David Lee",
      author_email     = "johnl@cs.wisc.edu",
      maintainer       = "johnl@cs.wisc.edu",
      url              = "none",
      packages         = ["ellnet"],
      scripts          = ["ellnetfs", ]
     )

