# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import logging

import routes

from glance.api.v1 import images
from glance.common import wsgi

logger = logging.getLogger('glance.api.v1')


class API(wsgi.Router):

    """WSGI router for Glance v1 API requests."""

    def __init__(self, options):
        self.options = options
        mapper = routes.Mapper()
        controller = images.Controller(options)
        mapper.resource("image", "images", controller=controller,
                       collection={'detail': 'GET'})
        mapper.connect("/", controller=controller, action="index")
        mapper.connect("/images/{id}", controller=controller, action="meta",
                       conditions=dict(method=["HEAD"]))
        super(API, self).__init__(mapper)


def app_factory(global_conf, **local_conf):
    """paste.deploy app factory for creating Glance API server apps"""
    conf = global_conf.copy()
    conf.update(local_conf)
    return API(conf)
