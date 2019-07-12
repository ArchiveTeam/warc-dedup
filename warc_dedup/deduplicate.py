import datetime
import os
import re
import urllib.parse

from warcio.archiveiterator import ArchiveIterator
from warcio.warcwriter import WARCWriter

from warc_dedup.log import Log
from warc_dedup.utils import get


class Warc:
    def __init__(self, warc_source: str, warc_target: str=None):
        self.warc_source = warc_source
        self.warc_target = warc_target
        self._response_records = {}
        self._log = Log()
        self._log.log('Original WARC file is {}.'.format(self.warc_source))
        self._log.log('Deduplicated WARC file is {}.'.format(self.warc_target))
        if os.path.isfile(self.warc_target):
            self._log.log('File {} already exists.'.format(self.warc_target))
            raise Exception('File {} already exists.'.format(self.warc_target))

    def deduplicate(self):
        self._log.log('Start deduplication process.')
        with open(self.warc_source, 'rb') as s, \
                open(self.warc_target, 'wb') as t:
            writer = WARCWriter(filebuf=t, gzip=self.warc_target.endswith('.gz'))
            for record in ArchiveIterator(s):
                url = record.rec_headers.get_header('WARC-Target-URI')
                record_id = record.rec_headers.get_header('WARC-Record-ID')
                self._log.log('Processing record {}.'.format(record_id))
                if url is not None and url.startswith('<'):
                    url = re.search('^<(.+)>$', url).group(1)
                    self._log.log('Replacing URL in record {} with {}.'
                                  .format(record_id, url))
                    record.rec_headers.replace_header('WARC-Target-URI', url)
                if record.rec_headers.get_header('WARC-Type') == 'response':
                    self._log.log('Deduplicating record {}.'.format(record_id))
                    data = self.get_duplicate(record)
                    print(data)
                    if data:
                        self._log.log('Record {} is a duplicate from {}.'
                                      .format(record_id, data))
                        writer.write_record(
                            self.response_to_revisit(writer, record, data)
                        )
                    else:
                        if data is False:
                            self._log.log('Record {} could not be deduplicated.'
                                .format(record_id))
                        else:
                            self._log.log('Record {} is not a duplicate.'
                                .format(record_id))
                        self.register_response(record)
                        writer.write_record(record)
                elif record.rec_headers.get_header('WARC-Type') == 'warcinfo':
                    self._log.set_warcinfo(record.rec_headers.get_header('WARC-Record-ID'))
                    record.rec_headers.replace_header('WARC-Filename', self.warc_target)
                    writer.write_record(record)
                else:
                    writer.write_record(record)
            self._log.log('Writing log to WARC.')
            writer.write_record(self._log.create_record(writer))

    def register_response(self, record):
        key = (
            record.rec_headers.get_header('WARC-Payload-Digest'),
            record.rec_headers.get_header('WARC-Target-URI')
        )
        self._response_records[key] = {
            'record-id': record.rec_headers.get_header('WARC-Record-ID'),
            'date': record.rec_headers.get_header('WARC-Date'),
            'target-uri': record.rec_headers.get_header('WARC-Target-URI')
        }

    @staticmethod
    def response_to_revisit(writer, record, data):
        warc_headers = record.rec_headers
        if 'record-id' in data and data['record-id'] is not None:
            warc_headers.replace_header('WARC-Refers-To', data['record-id'])
        warc_headers.replace_header('WARC-Refers-To-Date', data['date'])
        warc_headers.replace_header('WARC-Refers-To-Target-URI',
                                    data['target-uri'])
        warc_headers.replace_header('WARC-Type', 'revisit')
        warc_headers.replace_header('WARC-Truncated', 'length')
        warc_headers.replace_header('WARC-Profile',
                                    'http://netpreserve.org/warc/1.0/' \
                                    'revisit/identical-payload-digest')
        warc_headers.remove_header('WARC-Block-Digest')
        warc_headers.remove_header('Content-Length')
        return writer.create_warc_record(
            record.rec_headers.get_header('WARC-Target-URI'),
            'revisit',
            warc_headers=warc_headers,
            http_headers=record.http_headers
        )

    def get_duplicate(self, record):
        key = (
            record.rec_headers.get_header('WARC-Payload-Digest'),
            record.rec_headers.get_header('WARC-Target-URI')
        )
        if key in self._response_records:
            return self._response_records[key]
        return self.get_ia_duplicate(record)

    def get_ia_duplicate(self, record):
        date = record.rec_headers.get_header('WARC-Date')
        date = datetime.datetime.strptime(date, '%Y-%m-%dT%H:%M:%SZ')
        date = date.strftime('%Y%m%d%H%M%S')
        digest = record.rec_headers.get_header('WARC-Payload-Digest')
        uri = record.rec_headers.get_header('WARC-Target-URI')
        record_id = record.rec_headers.get_header('WARC-Record-ID')
        success, response = get(
            'http://wwwb-dedup.us.archive.org:8083/cdx/search'
            '?url={}'.format(urllib.parse.quote(uri)) +
            '&limit=100'
            '&filter=digest:{}'.format(digest.split(':')[1]) +
            '&fl=timestamp,original'
            '&to={}'.format(int(date) - 1) +
            '&filter=!mimetype:warc\/revisit',
            sleep_time=1,
            max_tries=10,
            timeout=10
        )
        self._log.log('Requested URL {}.'.format(response.url))
        if len(response.text.strip()) == 0:
            return None
        if 'org.archive.wayback.exception.RobotAccessControlException' in response.text:
            self._log.log('Record {} is blocked by robots.txt.'.format(record_id))
            return False
        if 'org.archive.wayback.exception.AdministrativeAccessControlException' in response.text:
            self._log.log('Record {} is excluded from the CDX API.'.format(record_id))
            return False
        if 'Requested Line is too large' in response.text:
            self._log.log('Record {} has a too large URL.'.format(record_id))
            return False
        if not success:
            self._log.log('Record {} got a bad CDX API response.'.format(record_id))
            return False
        for line in response.text.splitlines():
            if not re.search('^[0-9]{14}\s+https?://', line):
                continue
            break
        else:
            self._log.log('Record {} for an invalid CDX API response'.format(record_id))
            return False
        data = line.strip().split(' ', 1)
        return {
            'target-uri': data[1],
            'date': datetime.datetime.strptime(data[0], '%Y%m%d%H%M%S'). \
                strftime('%Y-%m-%dT%H:%M:%SZ')
        }

    @property
    def warc_target(self) -> str:
        return self._warc_target

    @warc_target.setter
    def warc_target(self, value: str):
        if value is not None:
            self._warc_target = value
        self._warc_target = create_warc_target(self.warc_source)


def create_warc_target(warc_source: str) -> str:
    if warc_source.endswith('.warc.gz'):
        return warc_source.rsplit('.', 2)[0] + '.deduplicated.warc.gz'
    elif warc_source.endswith('.warc'):
        return warc_source.rsplit('.', 1)[0] + '.deduplicated.warc'

