from __future__ import annotations

import json
from datetime import datetime
from queue import Queue
from threading import Event
from typing import Tuple
from urllib.request import urlopen, Request

from calibre.ebooks.metadata.book.base import Metadata
from calibre.ebooks.metadata.sources.base import Source
from calibre.utils.logging import ThreadSafeLog

__license__ = "MIT"
__copyright__ = "2024, Iceflower - iceflower@gmx.de"

# ToDo:
# Author(s)           : Hagedorn, N. H. & Prokipius, P. R. -> Vorname, Name
# Title               : Experimental evaluation of a breadboard heat and product-water removal system for  [...]
# Author(s)           : Hagedorn, N. H. & Prokipius, P. R.
# Tags                : Energy Production And Conversion
# Published           : 1977-05-01T00:00:00+00:00
# Identifiers         : ntrs:19770017648, nasa:TN-D-8485
# Comments            : A test program was conducted to evaluate the design of a heat and product-water [...]
# get NTRS '19770017648'


class Ntrs(Source):
    name = "NASA STI Repository"
    description = "Download metadata from NASA STI Repository."
    author = "Iceflower S; modified by feuille"
    version = (1, 0, 3)
    minimum_calibre_version = (7, 4, 0)

    capabilities = frozenset(["identify"])
    touched_fields = frozenset([
        "title", "authors", "identifier:ntrs", "identifier:nasa", "identifier:doi", "identifier:isbn", "comments",
        "publisher", "pubdate", "tags"
    ])

    NTRS_ID: str = "ntrs"
    NASA_ID: str = "nasa"
    PUB_URL: str = "https://ntrs.nasa.gov/citations"
    API_URL: str = "https://ntrs.nasa.gov/api"

    def get_book_url(self, identifiers: dict) -> Tuple[str, str, str] | None:
        ntrs_id: str | None = identifiers.get(Ntrs.NTRS_ID, None)
        if ntrs_id is not None:
            return Ntrs.NTRS_ID, ntrs_id, f"{Ntrs.PUB_URL}/{ntrs_id}"
        return None

    def id_from_url(self, url: str) -> str | None:
        if url.startswith(f"{Ntrs.PUB_URL}/"):
            return url[len(f"{Ntrs.PUB_URL}/"):]
        return None

    def identify(self, log: ThreadSafeLog, result_queue: Queue, abort: Event,
                 title: str | None = None, authors: list[str] | None = None,
                 identifiers: dict | None = None, timeout: int = 30) -> None:
        if authors is None:
            authors = []
        if title is None:
            title = ""
        meta: Metadata | None = None
        if identifiers is not None:
            for ident in [Ntrs.NTRS_ID, Ntrs.NASA_ID, "isbn", "doi"]:
                if ident not in identifiers:
                    continue
                try:
                    if ident == Ntrs.NTRS_ID:
                        log.debug(f"get NTRS '{identifiers[ident]}'")
                        meta = self._get_meta_from_ntrs_id(identifiers[ident], log=log)
                    else:
                        log.debug(f"search with '{ident}': '{identifiers[ident]}'")
                        meta = self._search(identifiers={ident: identifiers[ident]}, timeout=timeout, log=log)
                except Exception as ex:
                    log.exception(ex)
                    continue

                if meta is not None:
                    if not meta.has_identifier(ident) or meta.get_identifiers()[ident] != identifiers[ident]:
                        continue
                    result_queue.put(meta)
                    return
                if abort.is_set():
                    return

        try:
            log.debug(f"search with 'title': '{title}', 'authors': '{authors}'")
            meta = self._search(title=title, authors=authors, timeout=timeout, log=log)
        except Exception as ex:
            log.exception(ex)
            return

        if meta is not None:
            result_queue.put(meta)
            return

    def _search(self, title: str = "", authors: list[str] = "", identifiers: dict = None,
                timeout: int = 30, log = None) -> Metadata | None:
        params: dict = {
            "page": {
                # limit to one result
                "size": 1,
                "from": 0
            }
        }
        if title != "":
            params["title"] = title
        if len(authors) != 0:
            params["q"] = " ".join(authors)
        if identifiers is not None:
            if "isbn" in identifiers:
                params["q"] = f"{params.get('q', '')} {identifiers['isbn']}"
            if "doi" in identifiers:
                params["q"] = f"{params.get('q', '')} {identifiers['doi']}"
            if Ntrs.NASA_ID in identifiers:
                # do not prefix with NASA as it could be 'NASA-' or 'NASA/'
                params["q"] = f"{params.get('q', '')} {identifiers[Ntrs.NASA_ID]}"
        request: Request = Request(
            f"{Ntrs.API_URL}/citations/search",
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json"
            },
            data=json.dumps(params).encode("UTF-8"),
        )
        body: bytes
        log.debug(f"request: '{request}'")
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            if response.status != 200:
                raise Exception(f"failed to search: {body.decode()}")
        results: list[dict] = json.loads(body).get("results", [])
        if len(results) > 0:
            return self._parse_meta_from_dict(results[0], log)
        return None

    def _get_meta_from_ntrs_id(self, ntrs_id: int, timeout: int = 30, log: log=ThreadSafeLog) -> Metadata | None:
        request: Request = Request(f"{Ntrs.API_URL}/citations/{ntrs_id}", method="GET",
                                   headers={"Accept": "application/json"})
        body: bytes
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            if response.status == 404:
                return None
            if response.status != 200:
                raise Exception(f"failed to get meta from NTRS: {body.decode()}")
        return self._parse_meta_from_dict(json.loads(body), log)

    def _parse_meta_from_dict(self, data: dict, log) -> Metadata:
        log.debug(f"data': '{data}'")
        # data': '{'_meta': {'score': 65.544174}, 'copyright': {'determinationType': 'GOV_PUBLIC_USE_PERMITTED',
        # 'thirdPartyContentCondition': 'NOT_SET'}, 'subjectCategories': ['Energy Production And Conversion'],
        # 'exportControl': {'isExportControl': 'NO', 'ear': 'NO', 'itar': 'NO'},
        # 'distributionDate': '2019-06-20T00:00:00.0000000+00:00', 'otherReportNumbers': ['E-8822', 'NASA-TN-D-8485'],
        # 'fundingNumbers': [{'number': 'RTOP 506-23', 'type': 'PROJECT'}], 'title': 'Experimental ...',
        # 'stiType': 'OTHER', 'distribution': 'PUBLIC', 'submittedDate': '2013-09-03T18:05:00.0000000+00:00',
        # 'authorAffiliations': [
        # {'sequence': 0, 'submissionId': 19770017648,
        # 'meta': {'author': {'name': 'Hagedorn, N. H.'},
        # 'organization': {'name': 'NASA Lewis Research Center', 'location': 'Cleveland, OH, United States'}},
        # 'id': '819c0fbf4f64418780be10e0066fc654'},
        # {'sequence': 1, 'submissionId': 19770017648, 'meta': {'author': {'name': 'Prokipius, P. R.'},
        # 'organization': {'name': 'NASA Lewis Research Center', 'location': 'Cleveland, OH, United States'}},
        # 'id': 'e6016167d9404f47a3729ec5dcd8d5c7'}], 'stiTypeDetails': 'Other - NASA Technical Note (TN)',
        # 'technicalReviewType': 'TECHNICAL_REVIEW_TYPE_NONE', 'modified': '2022-11-19T05:48:05.9618800+00:00',
        # 'id': 19770017648, 'legacyMeta': {'__type': 'LegacyMetaIndex, StrivesApi.ServiceModel',
        # 'accessionNumber': '77N24592'}, 'created': '2013-09-03T18:05:00.0000000+00:00',
        # 'center': {'code': 'CDMS', 'name': 'Legacy CDMS', 'id': '092d6e0881874968859b972d39a888dc'},
        # 'onlyAbstract': False, 'sensitiveInformation': 2, 'abstract': 'A test program ....',
        # 'isLessonsLearned': False, 'disseminated': 'DOCUMENT_AND_METADATA',
        # 'publications': [{'submissionId': 19770017648, 'id': 'fcf04e0afda642c6ac0949a1ad0c546b',
        # 'publicationDate': '1977-05-01T00:00:00.0000000+00:00'}], 'status': 'CURATED', 'related': [],
        # 'downloads': [{'draft': False, 'mimetype': 'application/pdf', 'name': '19770017648.pdf', 'type': 'STI',
        # 'links': {'original': '/api/citations/19770017648/downloads/19770017648.pdf',
        # 'pdf': '/api/citations/19770017648/downloads/19770017648.pdf',
        # 'fulltext': '/api/citations/19770017648/downloads/19770017648.txt'}}], 'downloadsAvailable': True,
        # 'index': 'submissions-2024-02-08-05-28'}'
        authors: list[str] = []
        for author in data.get("authorAffiliations", []):
            name: str = author.get("meta", {}).get("author", {}).get("name", "")
            if name != "":
                # 'Hagedorn, N. H.'
                if ', ' in name:
                    split_pos = name.find(', ')
                    name = name[split_pos + 2:] + ' ' + name[:split_pos]
                authors.append(name)
        meta: Metadata = Metadata(data.get("title", ""), authors)
        meta.comments = data.get("abstract", "")
        for keyword in data.get("keywords", []):
            meta.tags.append(keyword)
        for keyword in data.get("subjectCategories", []):
            meta.tags.append(keyword)
        if "id" in data:
            meta.set_identifier(Ntrs.NTRS_ID, str(data["id"]))
        for rep_num in data.get("otherReportNumbers", []):
            if rep_num.startswith("NASA-") or rep_num.startswith("NASA/"):
                meta.set_identifier(Ntrs.NASA_ID, rep_num[5:])
                break
        if len(data.get("stiTypeDetails", [])) > 0:
            meta.series = data.get("stiTypeDetails")
            if 'nasa' in meta.get_identifiers():
                # nasa:TN-D-8485
                series_index_str = ''.join(filter(str.isdigit, str(meta.get_identifiers()['nasa'])))
                if len(series_index_str) > 0:
                    meta.series_index = float(series_index_str)
        if len(data.get("publications", [])) > 0:
            pub = data["publications"][0]
            if "isbn" in pub:
                meta.isbn = pub["isbn"].replace("-", "")
            if "doi" in pub:
                meta.set_identifier("doi", pub["doi"])
            if "publicationDate" in pub:
                meta.pubdate = datetime.fromisoformat(pub["publicationDate"])
            if "publisher" in pub:
                meta.publisher = pub["publisher"]

        return meta
