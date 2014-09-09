# Licensed under a 3-clause BSD style license - see LICENSE.rst
from __future__ import print_function
import time
import sys
import os.path
import webbrowser
import getpass
import warnings
import keyring
import numpy as np
import re
from bs4 import BeautifulSoup

from astropy.extern.six import BytesIO
from astropy.extern import six
from astropy.table import Table, Column
from astropy import log
import astropy.io.votable as votable

from ..exceptions import LoginError, RemoteServiceError
from ..utils import schema, system_tools
from ..utils import commons
from ..utils.process_asyncs import async_to_sync
from ..query import BaseQuery, QueryWithLogin, suspend_cache
from . import conf

__doctest_skip__ = ['AlmaClass.*']


@async_to_sync
class AlmaClass(BaseQuery):

    ROW_LIMIT = conf.row_limit
    TIMEOUT = conf.timeout
    archive_url = conf.archive_url

    def __init__(self):
        super(AlmaClass, self).__init__()

    def query_object_async(self, object_name, cache=True, public=True,
                           science=True):
        """
        Query the archive with a source name
        """

        payload = {'source_name_sesame': object_name,}

        return self.query_async(payload, cache=cache, public=public,
                                science=science)

    def query_region_async(self, coordinate, radius, cache=True, public=True,
                           science=True):
        """

        """
        cstr = coordinate.fk5.to_string(style='hmsdms', sep=':')
        rdc = "{cstr}, {rad}".format(cstr, radius.to(u.deg).value)

        payload = {'raDecCoordinates': rdc}

        return self.query_async(payload, cache=cache, public=public,
                                science=science)

    def query_async(self, payload, cache=True, public=True, science=True):
        """
        Perform a generic query with user-specified payload
        """
        url = os.path.join(self.archive_url, 'aq', 'search.votable')

        payload.update({'viewFormat':'raw',
                        'download':'true',})
        if public:
            payload['publicFilterFlag'] = 'public'
        if science:
            payload['scan_intent-asu'] = '=*TARGET*'

        response = self._request('GET', url, params=payload,
                                 timeout=self.TIMEOUT, cache=cache)

        return response

    def stage_data(self, uids, cache=False):

        #s = requests.Session()
        #response = s.post('http://almascience.eso.org/rh/submission', data=payload)
        #login = s.get('http://almascience.eso.org/rh/login')
        #scheck = s.get(login.url)
        #req = s.get('http://almascience.eso.org/rh/requests')
        #scheck = s.get(login.url, data={'service':'http://almascience.eso.org/rh/j_spring_cas_security_check'})
        #sub = s.get('http://almascience.eso.org/rh/submission/e98497ee-f094-4fe4-8ea8-d4ae01d1685d')
        #data = s.get('http://almascience.eso.org/rh/requests/anonymous/429721782')

        log.info("Staging files...")

        url = os.path.join(self.archive_url, 'rh', 'submission')
        #'ALMA+uid___A002_X391d0b_X7b'
        #payload = [('dataset','ALMA+'+clean_uid(uid)) for uid in uids]
        payload = {'dataset':['ALMA+'+clean_uid(uid) for uid in uids]}

        self._staging_log = {}
        
        # Request staging for the UIDs
        response = self._request('POST', url, data=payload,
                                 timeout=self.TIMEOUT, cache=cache)
        self._staging_log['initial_response'] = response

        request_id = response.url.split("/")[-2]
        self._staging_log['request_id'] = request_id

        login = self._request('GET', 'http://almascience.eso.org/rh/login',
                              cache=False) # ALWAYS False here

        scheck = self._request('GET', login.url,
                               data={'service':'http://almascience.eso.org/rh/j_spring_cas_security_check'},
                               cache=cache)

        # Submit a request for the specific request ID identified above
        submission_url = os.path.join(self.archive_url, 'rh', 'requests',
                                      request_id)
        self._staging_log['submission_url'] = submission_url
        submission = self._request('GET', submission_url, cache=cache)
        self._staging_log['submission'] = submission
        assert 'j_spring_cas_security_check' not in submission.url

        data_list_url = submission.url

        data_list_page = self._request('GET', data_list_url, cache=cache)
        self._staging_log['data_list_page'] = data_list_page

        root = BeautifulSoup(data_list_page.content, 'html5lib')

        data_table = root.findAll('table', class_='list', id='report')[0]
        hrefs = data_table.findAll('a')

        data_file_urls = [a['href'] for a in hrefs
                          if not a['href'].endswith('script')]

        return data_file_urls

    def download_data(self, uids, cache=True):

        files = self.stage_data(uids, cache=cache)

        log.info("Downloading files...")
        downloaded_files = []
        for fileLink in files:
            filename = self._request("GET", fileLink, save=True)
            downloaded_files.append(filename)

        return downloaded_files

    def _parse_result(self, response, verbose=False):
        """
        Parse a VOtable response
        """
        if not verbose:
            commons.suppress_vo_warnings()

        tf = six.BytesIO(response.content)
        vo_tree = votable.parse(tf, pedantic=False, invalid='mask')
        first_table = vo_tree.get_first_table()
        table = first_table.to_table()
        return table

Alma = AlmaClass()

def clean_uid(uid):
    """
    Return a uid with all unacceptable characters replaced with underscores
    """
    return uid.replace("/","_").replace(":","_")
