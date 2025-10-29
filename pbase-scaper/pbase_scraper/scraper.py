from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Set, Tuple
from urllib.parse import urlparse, urlunparse

from bs4 import BeautifulSoup

from .client import PBaseClient

logger = logging.getLogger(__name__)

SIZE_ORDER: Sequence[str] = ("original", "large", "medium", "small")


@dataclass
class ImageDownload:
    """Represents a resolved image ready for download."""

    url: str
    filename: str
    referer: str


class PBaseScraper:
    """Scrape galleries and download original-sized images."""

    def __init__(self, client: PBaseClient, *, output_dir: Path) -> None:
        self.client = client
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.visited_galleries: Set[str] = set()
        self.visited_images: Set[str] = set()
        self._filename_cache: Set[str] = set()

    def scrape(self, start_paths: Optional[Sequence[str]] = None) -> None:
        """Scrape galleries starting from the provided paths."""
        paths = list(start_paths) if start_paths else [f"{self.client.username}/root"]
        for path in paths:
            gallery_url = self._prepare_gallery_url(path)
            self._scrape_gallery(gallery_url, parent_title=None)

    def _scrape_gallery(self, url: str, parent_title: Optional[str] = None) -> None:
        normalized = self._normalize_gallery_url(url)
        if normalized in self.visited_galleries:
            logger.debug("Skipping already visited gallery %s", normalized)
            return
        logger.info("Scraping gallery %s", normalized)
        self.visited_galleries.add(normalized)

        soup = self.client.get_soup(normalized)
        gallery_title = self._determine_gallery_title(soup, normalized, parent_title)
        gallery_title = _clean_label(gallery_title) or gallery_title

        image_links, gallery_links = self._extract_gallery_contents(soup)
        logger.debug(
            "Found %d sub-galleries and %d images inside %s",
            len(gallery_links),
            len(image_links),
            normalized,
        )

        for image_link in sorted(image_links):
            self._scrape_image(image_link, gallery_title)

        for gallery_link in sorted(gallery_links):
            self._scrape_gallery(gallery_link, parent_title=gallery_title)

    def _scrape_image(self, url: str, gallery_title: Optional[str]) -> None:
        normalized = self._normalize_image_url(url)
        if normalized in self.visited_images:
            logger.debug("Skipping already visited image %s", normalized)
            return
        logger.info("Resolving image %s", normalized)
        self.visited_images.add(normalized)

        soup = self.client.get_soup(normalized)
        image = self._resolve_best_image(soup, normalized, gallery_title)
        if not image:
            logger.warning("Unable to resolve image source for %s", normalized)
            return

        destination = self._output_path(self.output_dir, image.filename)
        if destination.exists():
            logger.info("Skipping existing file %s", destination)
            return

        response = self.client.get(image.url, stream=True, headers={"Referer": image.referer})
        try:
            with destination.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 32):
                    if chunk:
                        handle.write(chunk)
            logger.info("Saved %s", destination)
        finally:
            response.close()

    def _extract_gallery_contents(self, soup: BeautifulSoup) -> Tuple[Set[str], Set[str]]:
        images: Set[str] = set()
        galleries: Set[str] = set()
        for link in self.client.iter_links(soup):
            parsed = urlparse(link)
            if not parsed.netloc or not parsed.netloc.endswith("pbase.com"):
                continue
            if self._is_image_link(parsed):
                images.add(self._normalize_image_url(link))
            elif self._is_gallery_link(parsed):
                galleries.add(self._normalize_gallery_url(link))
        return images, galleries

    def _resolve_best_image(
        self, soup: BeautifulSoup, referer: str, gallery_title: Optional[str]
    ) -> Optional[ImageDownload]:
        size_links = self._find_size_links(soup, referer)
        for size in SIZE_ORDER:
            candidate = size_links.get(size)
            if not candidate:
                continue
            resolved_url = self._resolve_binary_url(candidate, referer)
            if resolved_url:
                raw_filename = self._filename_from_url(resolved_url)
                if self._looks_like_placeholder(raw_filename):
                    logger.debug("Resolved %s -> %s but skipped placeholder", referer, raw_filename)
                    continue
                filename = self._compose_filename(soup, resolved_url, raw_filename, gallery_title)
                return ImageDownload(url=resolved_url, filename=filename, referer=referer)

        # fallback to main displayed image
        image_tag = self._select_display_image(soup)
        if image_tag and image_tag.get("src"):
            resolved_url = self._resolve_binary_url(image_tag["src"], referer)
            if resolved_url:
                raw_filename = self._filename_from_url(resolved_url)
                if self._looks_like_placeholder(raw_filename):
                    logger.debug("Fallback for %s resolved to placeholder %s; skipping", referer, raw_filename)
                else:
                    filename = self._compose_filename(soup, resolved_url, raw_filename, gallery_title)
                    return ImageDownload(url=resolved_url, filename=filename, referer=referer)
        return None

    def _find_size_links(self, soup: BeautifulSoup, referer: str) -> dict:
        size_links = {}
        for anchor in soup.find_all("a"):
            text = (anchor.text or "").strip().lower()
            href = (anchor.get("href") or "").strip()
            if not href:
                continue
            normalized_text = re.sub(r"\s+", " ", text)
            for size in SIZE_ORDER:
                if size in normalized_text:
                    size_links.setdefault(size, urljoin_referer(referer, href))
        return size_links

    def _resolve_binary_url(self, url: str, referer: Optional[str]) -> Optional[str]:
        base = referer or self.client.base_url
        absolute = urljoin_referer(base, url)
        headers = {"Referer": referer} if referer else None
        response = self.client.get(absolute, stream=True, headers=headers)
        content_type = (response.headers.get("Content-Type") or "").lower()
        if content_type.startswith("image/"):
            response.close()
            return absolute
        text = response.text
        response.close()
        soup = BeautifulSoup(text, "html.parser")
        tag = self._select_display_image(soup)
        if not tag or not tag.get("src"):
            return None
        return urljoin_referer(absolute, tag["src"])

    def _select_display_image(self, soup: BeautifulSoup) -> Optional[BeautifulSoup]:
        candidates = []
        for img in soup.find_all("img"):
            src = (img.get("src") or "").strip()
            if not src:
                continue
            src_lower = src.lower()
            if any(token in src_lower for token in ("m_pbase", "logo", "pixel.gif", "blank.gif")):
                continue
            width = _parse_int(img.get("width"))
            height = _parse_int(img.get("height"))
            if (width is None or height is None) and img.get("style"):
                style_width, style_height = _parse_dimensions_from_style(img["style"])
                width = width or style_width
                height = height or style_height
            dimension_score = (width or 0) * (height or 0)
            heuristic_bonus = 0
            if any(ext in src_lower for ext in (".jpg", ".jpeg", ".png", ".webp")):
                heuristic_bonus += 10_000_000
            if "/image/" in src_lower:
                heuristic_bonus += 5_000_000
            score = heuristic_bonus + dimension_score
            candidates.append((score, img))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _output_path(self, directory: Path, filename: str) -> Path:
        safe_name = sanitize_filename(filename)
        safe_name = self._truncate_filename(safe_name)
        candidate = directory / safe_name
        if not candidate.exists():
            self._filename_cache.add(candidate.name)
            return candidate
        stem = candidate.stem
        suffix = candidate.suffix
        counter = 1
        while True:
            new_candidate = directory / f"{stem}_{counter}{suffix}"
            if not new_candidate.exists():
                self._filename_cache.add(new_candidate.name)
                return new_candidate
            counter += 1

    def _normalize_gallery_url(self, url: str) -> str:
        parsed = urlparse(url)
        cleaned_path = _strip_view_suffix(parsed.path)
        normalized = parsed._replace(path=cleaned_path, query="", fragment="")
        return urlunparse(normalized)

    def _normalize_image_url(self, url: str) -> str:
        parsed = urlparse(url)
        cleaned_path = _strip_view_suffix(parsed.path)
        normalized = parsed._replace(path=cleaned_path, query="", fragment="")
        return urlunparse(normalized)

    def _prepare_gallery_url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return self._normalize_gallery_url(path)
        return self._normalize_gallery_url(f"{self.client.base_url.rstrip('/')}/{path.lstrip('/')}")

    def _filename_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        filename = os.path.basename(parsed.path)
        return filename or "image.jpg"

    def _compose_filename(
        self,
        soup: BeautifulSoup,
        url: str,
        fallback: str,
        gallery_title: Optional[str],
    ) -> str:
        raw_title = self._extract_image_title(soup)
        title = _clean_label(raw_title) if raw_title else ""
        if not title:
            title = fallback
        gallery_clean = _clean_label(gallery_title) if gallery_title else ""
        gallery_prefix = sanitize_filename(gallery_clean) if gallery_clean else ""
        safe_title = sanitize_filename(title)
        if not safe_title:
            return fallback
        extension = Path(urlparse(url).path).suffix or Path(fallback).suffix
        if extension:
            safe_title = safe_title.rstrip(". ")
            if not safe_title.lower().endswith(extension.lower()):
                safe_title = f"{safe_title}{extension}"
        if gallery_prefix and not safe_title.lower().startswith(gallery_prefix.lower()):
            safe_title = f"{gallery_prefix} - {safe_title}"
        return self._truncate_filename(safe_title)

    def _looks_like_placeholder(self, filename: str) -> bool:
        lowered = filename.lower()
        return lowered.startswith("m_pbase") or lowered in {"pixel.gif", "blank.gif"}

    def _truncate_filename(self, filename: str) -> str:
        """Ensure filenames stay under OS limits and keep the extension."""
        max_length = 120  # leaves headroom for directory path
        if len(filename) <= max_length:
            return filename
        path = Path(filename)
        stem = path.stem[: max(1, max_length - len(path.suffix) - 1)]
        truncated = f"{stem}{path.suffix}"
        if len(truncated) > max_length:
            truncated = truncated[:max_length]
        return truncated

    def _determine_gallery_title(
        self, soup: BeautifulSoup, url: str, parent_title: Optional[str]
    ) -> Optional[str]:
        title = self._extract_gallery_title(soup)
        if title:
            return title
        slug = self._gallery_slug_from_url(url)
        if slug.lower() == "root":
            return parent_title or "Root Gallery"
        derived = slug.replace("_", " ") if slug else parent_title
        cleaned = _clean_label(derived)
        return cleaned or parent_title

    def _extract_gallery_title(self, soup: BeautifulSoup) -> Optional[str]:
        selectors = [
            ("h1", {"id": "gallerytitle"}),
            ("h1", {"class": "gallerytitle"}),
            ("div", {"id": "gallerytitle"}),
            ("div", {"class": "gallerytitle"}),
            ("h1", {}),
            ("h2", {}),
        ]
        for name, attrs in selectors:
            element = soup.find(name, attrs=attrs or None)
            if not element:
                continue
            text = _clean_label(element.get_text(strip=True))
            if text:
                return text
        if soup.title:
            text = _clean_label(soup.title.get_text(strip=True))
            if text:
                return text.split("|")[0].strip()
        return None

    def _gallery_slug_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        cleaned_path = _strip_view_suffix(parsed.path)
        parts = [part for part in cleaned_path.split("/") if part]
        if not parts:
            return "root"
        if parts[-1].lower() in {"gallery", "galleries"} and len(parts) >= 2:
            return parts[-2]
        return parts[-1]

    def _extract_image_title(self, soup: BeautifulSoup) -> Optional[str]:
        selectors = [
            ("div", {"id": "imagecaption"}),
            ("div", {"class": "imagecaption"}),
            ("div", {"class": "caption"}),
            ("div", {"id": "caption"}),
            ("span", {"class": "caption"}),
            ("h1", {}),
            ("h2", {}),
        ]
        for name, attrs in selectors:
            element = soup.find(name, attrs=attrs or None)
            if not element:
                continue
            text = _clean_label(element.get_text(strip=True))
            if text:
                return text
        if soup.title:
            text = _clean_label(soup.title.get_text(strip=True))
            if text:
                return text.split("|")[0].strip()
        return None

    def _is_image_link(self, parsed) -> bool:
        path = parsed.path.lower()
        if "/image/" not in path:
            return False
        if any(part in path for part in ("/edit", "/delete", "/upload")):
            return False
        return True

    def _is_gallery_link(self, parsed) -> bool:
        path = _strip_view_suffix(parsed.path).strip("/")
        if not path:
            return False
        segments = [seg for seg in path.split("/") if seg]
        if not segments:
            return False
        if segments[0].lower() != self.client.username.lower():
            return False
        if "image" in (seg.lower() for seg in segments[1:]):
            return False
        forbidden = {
            "forum",
            "search",
            "logout",
            "login",
            "profile",
            "guestbook",
            "help",
            "recent",
            "slideshow",
            "upload",
            "edit",
            "view",
            "galleries",
            "statistics",
            "usage",
            "payment",
            "popular",
            "random",
        }
        if len(segments) >= 2 and segments[1].lower() in forbidden:
            return False
        # PBase exposes both /user/gallery/name and /user/name structures.
        return True


def urljoin_referer(base: str, url: str) -> str:
    from urllib.parse import urljoin

    if url.startswith(("http://", "https://")):
        return url
    return urljoin(base if base.endswith("/") else f"{base}/", url)


def sanitize_filename(name: str) -> str:
    safe = re.sub(r"[^\w.\-() ]+", "_", name)
    safe = re.sub(r"\s+", " ", safe).strip()
    return safe or "image.jpg"


def _parse_int(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_dimensions_from_style(style: str) -> Tuple[Optional[int], Optional[int]]:
    width = None
    height = None
    width_match = re.search(r"width:\s*(\d+)", style)
    height_match = re.search(r"height:\s*(\d+)", style)
    if width_match:
        width = _parse_int(width_match.group(1))
    if height_match:
        height = _parse_int(height_match.group(1))
    return width, height


def _clean_label(text: Optional[str]) -> str:
    if not text:
        return ""
    cleaned = str(text).strip()
    cleaned = re.sub(r"\s*photo\s*-\s*[^|]*photos at pbase\.com", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\|\s*pbase\.com.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*-\s*pbase\.com.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\|\s*$", "", cleaned)
    cleaned = cleaned.strip(" -–—")
    return cleaned


def _strip_view_suffix(path: str) -> str:
    """Normalize gallery paths that embed '&view=...' or similar suffixes."""
    if not path:
        return path
    # Treat '&' or ';' following the last slash as stylistic query parameters.
    segments = path.split("/")
    cleaned_segments = []
    for segment in segments:
        if "&" in segment:
            segment = segment.split("&", 1)[0]
        if ";" in segment:
            segment = segment.split(";", 1)[0]
        cleaned_segments.append(segment)
    cleaned_path = "/".join(cleaned_segments)
    # Collapse potential repeated slashes introduced by stripping.
    cleaned_path = re.sub(r"/{2,}", "/", cleaned_path)
    return cleaned_path.rstrip("/") if cleaned_path.endswith("/") and len(cleaned_path) > 1 else cleaned_path
