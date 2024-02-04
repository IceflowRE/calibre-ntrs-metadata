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


class Ntrs(Source):
    name = "NASA STI Repository"
    description = "Download metadata from NASA STI Repository."
    author = "Iceflower S"
    version = (1, 0, 0)
    minimum_calibre_version = (7, 4, 0)

    capabilities = frozenset(["identify"])
    touched_fields = frozenset([
        "title", "authors", "identifier:ntrs", "identifier:nasa", "identifier:doi", "identifier:isbn", "comments", "publisher", "pubdate", "tags"
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

    def identify(self, log: ThreadSafeLog, result_queue: Queue, abort: Event, title: str | None = None, authors: list[str] | None = None,
                 identifiers: dict | None = None, timeout: int = 30) -> None:
        meta: Metadata | None = None
        if identifiers is not None:
            for ident in [Ntrs.NTRS_ID, Ntrs.NASA_ID, "isbn", "doi"]:
                if ident not in identifiers:
                    continue
                try:
                    if ident == Ntrs.NTRS_ID:
                        log.debug(f"get NTRS '{identifiers[ident]}'")
                        meta = self._get_meta_from_ntrs_id(identifiers[ident])
                    else:
                        log.debug(f"search with '{ident}': '{identifiers[ident]}'")
                        meta = self._search(identifiers={ident: identifiers[ident]}, timeout=timeout)
                except Exception as ex:
                    log.exception(ex)
                    continue

                if meta is not None and (not meta.has_identifier(ident) or meta.get_identifiers()[ident] != identifiers[ident]):
                    continue
                if meta is not None:
                    result_queue.put(meta)
                    return
                if abort.is_set():
                    return

        try:
            log.debug(f"search with 'title': '{title}', 'authors': '{authors}'")
            meta = self._search(title=title, authors=authors, timeout=timeout)
        except Exception as ex:
            log.exception(ex)
            return

        if meta is not None:
            result_queue.put(meta)
            return

    def _search(self, title: str = "", authors: list[str] = "", identifiers: dict = None, timeout: int = 30, log=None) -> Metadata | None:
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
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            if response.status != 200:
                raise Exception(f"failed to search: {body.decode()}")
        results: list[dict] = json.loads(body).get("results", [])
        if len(results) > 0:
            return self._parse_meta_from_dict(results[0])
        return None

    def _get_meta_from_ntrs_id(self, ntrs_id: int, timeout: int = 30) -> Metadata | None:
        request: Request = Request(f"{Ntrs.API_URL}/citations/{ntrs_id}", method="GET", headers={"Accept": "application/json"})
        body: bytes
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            if response.status == 404:
                return None
            if response.status != 200:
                raise Exception(f"failed to get meta from NTRS: {body.decode()}")
        return self._parse_meta_from_dict(json.loads(body))

    def _parse_meta_from_dict(self, data: dict) -> Metadata:
        authors: list[str] = []
        for author in data.get("authorAffiliations", []):
            name: str = author.get("meta", {}).get("author", {}).get("name", "")
            if name != "":
                authors.append(name)
        meta: Metadata = Metadata(data.get("title", ""), authors)
        meta.comments = data.get("abstract", "")
        for keyword in data.get("keywords", []):
            meta.tags.append(keyword)
        for keyword in data.get("subjectCategories", []):
            meta.tags.append(keyword)
        if "id" in data:
            meta.set_identifier(Ntrs.NTRS_ID, str(data["id"]))
        if len(data.get("publications", [])) > 0:
            pub = data["publications"][0]
            if "isbn" in pub:
                meta.isbn = pub["isbn"].replace("-", "")
            if "doi" in pub:
                meta.set_identifier("doi", pub["doi"])
            if "publicationDate" in pub:
                meta.pubdate = datetime.strptime(pub["publicationDate"][:10], "%Y-%m-%d")
            if "publisher" in pub:
                meta.publisher = pub["publisher"]
        for rep_num in data.get("otherReportNumbers", []):
            if rep_num.startswith("NASA-") or rep_num.startswith("NASA/"):
                meta.set_identifier(Ntrs.NASA_ID, rep_num[5:])
                break

        return meta
