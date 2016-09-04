# -*- coding: utf-8 -*-

from __future__ import (print_function, unicode_literals, absolute_import,
                        division)
from pusher.http import GET, POST, Request, request_method
from pusher.signature import sign, verify
from pusher.util import ensure_text, validate_channel, validate_socket_id, pusher_url_re, channel_name_re, join_attributes
from pusher.client import Client


import collections
import hashlib
import json
import os
import re
import six
import time


class PusherClient(Client):
    def __init__(self, app_id, key, secret, ssl=True, host=None, port=None, timeout=5, cluster=None,
                 json_encoder=None, json_decoder=None, backend=None, notification_host=None,
                 notification_ssl=True, **backend_options):
        super(PusherClient, self).__init__(
            app_id, key, secret, ssl,
            host, port, timeout, cluster,
            json_encoder, json_decoder, backend,
            **backend_options)

        if host:
            self._host = ensure_text(host, "host")
        elif cluster:
            self._host = six.text_type("api-%s.pusher.com") % ensure_text(cluster, "cluster")
        else:
            self._host = six.text_type("api.pusherapp.com")


    @request_method
    def trigger(self, channels, event_name, data, socket_id=None):
        if isinstance(channels, six.string_types):
            channels = [channels]

        if isinstance(channels, dict) or not isinstance(channels, (collections.Sized, collections.Iterable)):
            raise TypeError("Expected a single or a list of channels")

        if len(channels) > 10:
            raise ValueError("Too many channels")

        channels = list(map(validate_channel, channels))

        event_name = ensure_text(event_name, "event_name")

        if len(event_name) > 200:
            raise ValueError("event_name too long")

        data = self._data_to_string(data)

        if len(data) > 10240:
            raise ValueError("Too much data")

        params = {
            'name': event_name,
            'channels': channels,
            'data': data
        }
        if socket_id:
            params['socket_id'] = validate_socket_id(socket_id)

        return Request(self, POST, "/apps/%s/events" % self.app_id, params)


    @request_method
    def trigger_batch(self, batch=[], already_encoded=False):
        '''
        Trigger multiple events with a single HTTP call.

        http://pusher.com/docs/rest_api#method-post-batch-events
        '''

        if not already_encoded:
            for event in batch:
                event['data'] = self._data_to_string(event['data'])

        params = {
            'batch': batch
        }

        return Request(self, POST, "/apps/%s/batch_events" % self.app_id, params)


    @request_method
    def channels_info(self, prefix_filter=None, attributes=[]):
        '''
        Get information on multiple channels, see:

        http://pusher.com/docs/rest_api#method-get-channels
        '''
        params = {}
        if attributes:
            params['info'] = join_attributes(attributes)
        if prefix_filter:
            params['filter_by_prefix'] = ensure_text(prefix_filter, "prefix_filter")
        return Request(self, GET, six.text_type("/apps/%s/channels") % self.app_id, params)


    @request_method
    def channel_info(self, channel, attributes=[]):
        '''
        Get information on a specific channel, see:

        http://pusher.com/docs/rest_api#method-get-channel
        '''
        validate_channel(channel)

        params = {}
        if attributes:
            params['info'] = join_attributes(attributes)
        return Request(self, GET, "/apps/%s/channels/%s" % (self.app_id, channel), params)


    @request_method
    def users_info(self, channel):
        '''
        Fetch user ids currently subscribed to a presence channel

        http://pusher.com/docs/rest_api#method-get-users
        '''
        validate_channel(channel)

        return Request(self, GET, "/apps/%s/channels/%s/users" % (self.app_id, channel))


    def authenticate(self, channel, socket_id, custom_data=None):
        """Used to generate delegated client subscription token.

        :param channel: name of the channel to authorize subscription to
        :param socket_id: id of the socket that requires authorization
        :param custom_data: used on presence channels to provide user info
        """
        channel = validate_channel(channel)

        if not channel_name_re.match(channel):
            raise ValueError('Channel should be a valid channel, got: %s' % channel)

        socket_id = validate_socket_id(socket_id)

        if custom_data:
            custom_data = json.dumps(custom_data, cls=self._json_encoder)

        string_to_sign = "%s:%s" % (socket_id, channel)

        if custom_data:
            string_to_sign += ":%s" % custom_data

        signature = sign(self.secret, string_to_sign)

        auth = "%s:%s" % (self.key, signature)
        result = {'auth': auth}

        if custom_data:
            result['channel_data'] = custom_data

        return result


    def validate_webhook(self, key, signature, body):
        """Used to validate incoming webhook messages. When used it guarantees
        that the sender is Pusher and not someone else impersonating it.

        :param key: key used to sign the body
        :param signature: signature that was given with the body
        :param body: content that needs to be verified
        """
        key = ensure_text(key, "key")
        signature = ensure_text(signature, "signature")
        body = ensure_text(body, "body")

        if key != self.key:
            return None

        if not verify(self.secret, body, signature):
            return None

        try:
            body_data = json.loads(body, cls=self._json_decoder)
        except ValueError:
            return None

        time_ms = body_data.get('time_ms')
        if not time_ms:
            return None

        if abs(time.time()*1000 - time_ms) > 300000:
            return None

        return body_data


    def _data_to_string(self, data):
        if isinstance(data, six.string_types):
            return ensure_text(data, "data")
        else:
            return json.dumps(data, cls=self._json_encoder)
