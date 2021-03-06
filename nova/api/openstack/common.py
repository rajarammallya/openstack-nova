# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

import re
from urlparse import urlparse
from xml.dom import minidom

import webob

from nova import exception
from nova import flags
from nova import log as logging
from nova.api.openstack import wsgi


LOG = logging.getLogger('nova.api.openstack.common')
FLAGS = flags.FLAGS


XML_NS_V10 = 'http://docs.rackspacecloud.com/servers/api/v1.0'
XML_NS_V11 = 'http://docs.openstack.org/compute/api/v1.1'


def get_pagination_params(request):
    """Return marker, limit tuple from request.

    :param request: `wsgi.Request` possibly containing 'marker' and 'limit'
                    GET variables. 'marker' is the id of the last element
                    the client has seen, and 'limit' is the maximum number
                    of items to return. If 'limit' is not specified, 0, or
                    > max_limit, we default to max_limit. Negative values
                    for either marker or limit will cause
                    exc.HTTPBadRequest() exceptions to be raised.

    """
    params = {}
    for param in ['marker', 'limit']:
        if not param in request.GET:
            continue
        try:
            params[param] = int(request.GET[param])
        except ValueError:
            msg = _('%s param must be an integer') % param
            raise webob.exc.HTTPBadRequest(explanation=msg)
        if params[param] < 0:
            msg = _('%s param must be positive') % param
            raise webob.exc.HTTPBadRequest(explanation=msg)

    return params


def limited(items, request, max_limit=FLAGS.osapi_max_limit):
    """
    Return a slice of items according to requested offset and limit.

    @param items: A sliceable entity
    @param request: `wsgi.Request` possibly containing 'offset' and 'limit'
                    GET variables. 'offset' is where to start in the list,
                    and 'limit' is the maximum number of items to return. If
                    'limit' is not specified, 0, or > max_limit, we default
                    to max_limit. Negative values for either offset or limit
                    will cause exc.HTTPBadRequest() exceptions to be raised.
    @kwarg max_limit: The maximum number of items to return from 'items'
    """
    try:
        offset = int(request.GET.get('offset', 0))
    except ValueError:
        msg = _('offset param must be an integer')
        raise webob.exc.HTTPBadRequest(explanation=msg)

    try:
        limit = int(request.GET.get('limit', max_limit))
    except ValueError:
        msg = _('limit param must be an integer')
        raise webob.exc.HTTPBadRequest(explanation=msg)

    if limit < 0:
        msg = _('limit param must be positive')
        raise webob.exc.HTTPBadRequest(explanation=msg)

    if offset < 0:
        msg = _('offset param must be positive')
        raise webob.exc.HTTPBadRequest(explanation=msg)

    limit = min(max_limit, limit or max_limit)
    range_end = offset + limit
    return items[offset:range_end]


def limited_by_marker(items, request, max_limit=FLAGS.osapi_max_limit):
    """Return a slice of items according to the requested marker and limit."""
    params = get_pagination_params(request)

    limit = params.get('limit', max_limit)
    marker = params.get('marker')

    limit = min(max_limit, limit)
    start_index = 0
    if marker:
        start_index = -1
        for i, item in enumerate(items):
            if item['id'] == marker:
                start_index = i + 1
                break
        if start_index < 0:
            msg = _('marker [%s] not found') % marker
            raise webob.exc.HTTPBadRequest(explanation=msg)
    range_end = start_index + limit
    return items[start_index:range_end]


def get_id_from_href(href):
    """Return the id portion of a url as an int.

    Given: 'http://www.foo.com/bar/123?q=4'
    Returns: 123

    In order to support local hrefs, the href argument can be just an id:
    Given: '123'
    Returns: 123

    """
    if re.match(r'\d+$', str(href)):
        return int(href)
    try:
        return int(urlparse(href).path.split('/')[-1])
    except:
        LOG.debug(_("Error extracting id from href: %s") % href)
        raise ValueError(_('could not parse id from href'))


def remove_version_from_href(href):
    """Removes the first api version from the href.

    Given: 'http://www.nova.com/v1.1/123'
    Returns: 'http://www.nova.com/123'

    Given: 'http://www.nova.com/v1.1'
    Returns: 'http://www.nova.com'

    """
    try:
        #removes the first instance that matches /v#.#/
        new_href = re.sub(r'[/][v][0-9]+\.[0-9]+[/]', '/', href, count=1)

        #if no version was found, try finding /v#.# at the end of the string
        if new_href == href:
            new_href = re.sub(r'[/][v][0-9]+\.[0-9]+$', '', href, count=1)
    except:
        LOG.debug(_("Error removing version from href: %s") % href)
        msg = _('could not parse version from href')
        raise ValueError(msg)

    if new_href == href:
        msg = _('href does not contain version')
        raise ValueError(msg)
    return new_href


def get_version_from_href(href):
    """Returns the api version in the href.

    Returns the api version in the href.
    If no version is found, 1.0 is returned

    Given: 'http://www.nova.com/123'
    Returns: '1.0'

    Given: 'http://www.nova.com/v1.1'
    Returns: '1.1'

    """
    try:
        #finds the first instance that matches /v#.#/
        version = re.findall(r'[/][v][0-9]+\.[0-9]+[/]', href)
        #if no version was found, try finding /v#.# at the end of the string
        if not version:
            version = re.findall(r'[/][v][0-9]+\.[0-9]+$', href)
        version = re.findall(r'[0-9]+\.[0-9]', version[0])[0]
    except IndexError:
        version = '1.0'
    return version


class MetadataXMLDeserializer(wsgi.MetadataXMLDeserializer):

    def _extract_metadata_container(self, datastring):
        dom = minidom.parseString(datastring)
        metadata_node = self.find_first_child_named(dom, "metadata")
        metadata = self.extract_metadata(metadata_node)
        return {'body': {'metadata': metadata}}

    def create(self, datastring):
        return self._extract_metadata_container(datastring)

    def update_all(self, datastring):
        return self._extract_metadata_container(datastring)

    def update(self, datastring):
        dom = minidom.parseString(datastring)
        metadata_item = self.extract_metadata(dom)
        return {'body': {'meta': metadata_item}}


class MetadataHeadersSerializer(wsgi.ResponseHeadersSerializer):

    def delete(self, response, data):
        response.status_int = 204


class MetadataXMLSerializer(wsgi.XMLDictSerializer):
    def __init__(self, xmlns=wsgi.XMLNS_V11):
        super(MetadataXMLSerializer, self).__init__(xmlns=xmlns)

    def _meta_item_to_xml(self, doc, key, value):
        node = doc.createElement('meta')
        doc.appendChild(node)
        node.setAttribute('key', '%s' % key)
        text = doc.createTextNode('%s' % value)
        node.appendChild(text)
        return node

    def meta_list_to_xml(self, xml_doc, meta_items):
        container_node = xml_doc.createElement('metadata')
        for (key, value) in meta_items:
            item_node = self._meta_item_to_xml(xml_doc, key, value)
            container_node.appendChild(item_node)
        return container_node

    def _meta_list_to_xml_string(self, metadata_dict):
        xml_doc = minidom.Document()
        items = metadata_dict['metadata'].items()
        container_node = self.meta_list_to_xml(xml_doc, items)
        xml_doc.appendChild(container_node)
        self._add_xmlns(container_node)
        return xml_doc.toprettyxml(indent='    ', encoding='UTF-8')

    def index(self, metadata_dict):
        return self._meta_list_to_xml_string(metadata_dict)

    def create(self, metadata_dict):
        return self._meta_list_to_xml_string(metadata_dict)

    def update_all(self, metadata_dict):
        return self._meta_list_to_xml_string(metadata_dict)

    def _meta_item_to_xml_string(self, meta_item_dict):
        xml_doc = minidom.Document()
        item_key, item_value = meta_item_dict.items()[0]
        item_node = self._meta_item_to_xml(xml_doc, item_key, item_value)
        xml_doc.appendChild(item_node)
        self._add_xmlns(item_node)
        return xml_doc.toprettyxml(indent='    ', encoding='UTF-8')

    def show(self, meta_item_dict):
        return self._meta_item_to_xml_string(meta_item_dict['meta'])

    def update(self, meta_item_dict):
        return self._meta_item_to_xml_string(meta_item_dict['meta'])

    def default(self, *args, **kwargs):
        return ''
