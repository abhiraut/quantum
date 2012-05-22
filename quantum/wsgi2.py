# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
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

"""
Utility methods for working with WSGI servers redux
"""
import json
import logging

import webob
import webob.dec

from quantum.common import exceptions as exception
from quantum import wsgi


LOG = logging.getLogger(__name__)


class Request(webob.Request):
    """Add some Openstack API-specific logic to the base webob.Request."""

    def best_match_content_type(self):
        supported = ('application/json')
        return self.accept.best_match(supported,
                                      default_match='applicaton/json')

    @property
    def context(self):
        #this is here due to some import loop issues.(mdragon)
        from quantum.context import get_admin_context
        #Eventually the Auth[NZ] code will supply this. (mdragon)
        #when that happens this if block should raise instead.
        if 'quantum.context' not in self.environ:
            self.environ['quantum.context'] = get_admin_context()
        return self.environ['quantum.context']


def Resource(controller, deserializer, serializer):
    def _args(request):
        route_args = request.environ.get('wsgiorg.routing_args')
        if not route_args:
            return {}

        return route_args[1].copy()

    @webob.dec.wsgify(RequestClass=Request)
    def resource(request):
        args = _args(request)

        # NOTE(jkoelker) by now the controller is already found, remove
        #                it from the args if it is in the matchdict
        args.pop('controller', None)
        fmt = args.pop('format', None)
        action = args.pop('action', None)

        LOG.debug('*' * 80)
        LOG.debug(fmt)
        LOG.debug(action)

    return resource


class ResponseSerializer(object):
    def __init__(self, serializers=None):
        self.serializers = {
            'application/json': lambda x: json.dumps(x),
            'application/xml': wsgi.XMLDictSerializer()
        }
        self.response_status = dict(create=201, update=202, delete=204)
        self.serializers.update(serializers or {})

    def __call__(self, request):
        return self.serialize(request)

    def serialize(self, response_data, content_type, action):
        response = webob.Response()
        serializer = self.serializers.get(content_type, None)
        if not serializer:
            raise exception.InvalidContentType(content_type=content_type)
        response.body = serializer(response_data)
        response.status_int = self.response_status.get(action, 200)
        return response


class RequestDeserializer(object):
    def __init__(self, deserializers=None):
        self.deserializers = {
            'application/xml': wsgi.XMLDeserializer(),
            'application/json': lambda x: json.loads(x)
        }
        self.deserializers.update(deserializers or {})

    def __call__(self, request):
        return self.deserialize(request)

    def deserialize(self, request):
        args = environ['wsgiorg.routing_args'][1].copy()
        for key in ['format', 'controller']:
            args.pop(key, None)
        action = args.pop('action', None)

        action_args.update(self.deserialize_body(request, action))

        accept = request.best_match_content_type()

        return (action, args, accept)

    def deserialize_body(self, request, action):
        if len(request.body) == 0:
            LOG.debug(_("Empty request body"))
            return {}

        content_type = request.best_match_content_type()
        deserializer = self.deserializers.get(content_type)
        if not deserializer:
            LOG.debug(_("Unrecognized Content-Type provided in request"))
            raise exception.InvalidContentType(content_type)

        try:
            return deserializer(request.body, action)
        except exception.InvalidContentType:
            LOG.debug(_("Unable to deserialize body as provided Content-Type"))
            raise
