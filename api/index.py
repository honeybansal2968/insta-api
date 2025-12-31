import json
import os
import re
import time
from typing import Dict, Tuple
from urllib.parse import quote

import requests
from flask import Flask, jsonify, request
import instaloader
from rocketapi import InstagramAPI

app = Flask(__name__)

_INSTAGRAM_TOKEN = os.environ.get(
    "INSTAGRAM_API_TOKEN",
    "EAATAvWG95ZCkBQUiaZBXroBfy9M6eRagVafS5P3TDzo6wNbmv78ZAY6O7eJgi0gSZBFhb3O1OygTU5On7TJLhJqgwZBSz8wyHk9Ij4Q0lYcfIsZAUSSpRJSJj1PA0fUNJWbRwJZB5QZCMktZC8u0d84ZBQW9kZCfgyaOvCF5NIi4iHF1OzhrHvp0PrnqLOjRDC3nwZDZD",
)
instagram_api = InstagramAPI(token=_INSTAGRAM_TOKEN)
_instaloader = instaloader.Instaloader()

_INSTALOADER_USERNAME = os.environ.get("INSTALOADER_USERNAME", "honeybansal23")
_INSTALOADER_SESSION_FILE = os.environ.get(
    "INSTALOADER_SESSION_FILE", "/session-honeybansal23"
)
_MEDIA_INFO_CACHE_TTL = int(os.environ.get("MEDIA_INFO_CACHE_TTL", "300"))
_media_info_cache: Dict[str, Tuple[float, dict]] = {}

_REEL_DOC_ID = os.environ.get("REEL_DOC_ID", "24368985919464652")
_DEFAULT_HEADERS = {
    "content-type": "application/x-www-form-urlencoded",
    "user-agent": os.environ.get(
        "INSTAGRAM_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    ),
    "x-csrftoken": os.environ.get("INSTAGRAM_CSRF_TOKEN", "UNzTaJyJwVBCzd50o74UbpC7nrEdNWMd"),
    "x-ig-app-id": os.environ.get("INSTAGRAM_APP_ID", "936619743392459"),
}

if _INSTALOADER_USERNAME and _INSTALOADER_SESSION_FILE:
    try:
        _instaloader.load_session_from_file(
            _INSTALOADER_USERNAME, filename=_INSTALOADER_SESSION_FILE
        )
    except Exception as exc:  # pragma: no cover - instaloader session handling external
        app.logger.warning("Failed to load Instaloader session: %s", exc)


@app.get("/health")
def health_check():
    return jsonify({"status": "ok"})


@app.get("/media/<string:shortcode>")
def media_lookup(shortcode: str):
    try:
        media_id = instagram_api.get_media_id_by_shortcode(shortcode)
    except Exception as exc:  # pragma: no cover - rocketapi behavior external
        return jsonify({"error": str(exc)}), 500
    return jsonify({"shortcode": shortcode, "media_id": media_id})


@app.get("/media-info/<string:shortcode>")
def media_info(shortcode: str):
    now = time.time()
    cached = _media_info_cache.get(shortcode)
    if cached and now - cached[0] < _MEDIA_INFO_CACHE_TTL:
        return jsonify(cached[1])

    try:
        post = instaloader.Post.from_shortcode(_instaloader.context, shortcode)
        payload = {
            "shortcode": shortcode,
            "owner_username": post.owner_username,
            "caption": post.caption,
            "likes": post.likes,
            "comments": post.comments,
            "is_video": post.is_video,
            "media_url": post.video_url if post.is_video else post.url,
        }
        _media_info_cache[shortcode] = (now, payload)
    except Exception as exc:  # pragma: no cover - instaloader behavior external
        return jsonify({"error": str(exc)}), 500

    return jsonify(payload)


def extract_shortcode_from_url(url: str) -> str:
    cleaned = url.split("?")[0]
    pattern = r"instagram\.com/(?:[^/]+/)?(?:reel|p)/([^/?]+)"
    match = re.search(pattern, cleaned)
    if not match:
        raise ValueError("Invalid Instagram URL")
    return match.group(1)


def create_payload(shortcode: str) -> str:
    variables = json.dumps({"shortcode": shortcode})
    encoded_variables = quote(variables)
    return f"variables={encoded_variables}&doc_id={_REEL_DOC_ID}"


def extract_reel_data(data: dict) -> dict:
    try:
        item = data["data"]["xdt_api__v1__media__shortcode__web_info"]["items"][0]

        video_urls = []
        if "video_versions" in item:
            sorted_videos = sorted(
                item["video_versions"], key=lambda x: x.get("width", 0), reverse=True
            )
            video_urls = [video["url"] for video in sorted_videos]

        thumbnail_urls = []
        if "image_versions2" in item and "candidates" in item["image_versions2"]:
            sorted_images = sorted(
                item["image_versions2"]["candidates"],
                key=lambda x: x.get("width", 0),
                reverse=True,
            )
            thumbnail_urls = [img["url"] for img in sorted_images]

        audio_url = None
        if "extensions" in data and "all_video_dash_prefetch_representations" in data["extensions"]:
            for video_data in data["extensions"]["all_video_dash_prefetch_representations"]:
                for rep in video_data.get("representations", []):
                    if rep.get("mime_type") == "audio/mp4":
                        audio_url = rep.get("base_url")
                        break
                if audio_url:
                    break

        user_info = {}
        if "user" in item:
            user = item["user"]
            user_info = {
                "id": user.get("pk"),
                "username": user.get("username"),
                "full_name": user.get("full_name"),
                "profile_pic_url": user.get("profile_pic_url"),
                "is_verified": user.get("is_verified", False),
                "is_private": user.get("is_private", False),
            }

        reel_info = {
            "shortcode": item.get("code"),
            "id": item.get("id"),
            "taken_at": item.get("taken_at"),
            "like_count": item.get("like_count"),
            "comment_count": item.get("comment_count"),
            "view_count": item.get("view_count"),
            "has_audio": item.get("has_audio", False),
            "caption": item.get("caption", {}).get("text")
            if isinstance(item.get("caption"), dict)
            else None,
            "media_type": item.get("media_type"),
            "original_width": item.get("original_width"),
            "original_height": item.get("original_height"),
        }

        if "video_dash_manifest" in item:
            import xml.etree.ElementTree as ET  # noqa: WPS433

            try:
                manifest = ET.fromstring(item["video_dash_manifest"])
                duration = manifest.attrib.get("mediaPresentationDuration")
                if duration:
                    reel_info["duration"] = duration
            except Exception:  # pragma: no cover - defensive parsing
                pass

        clips_metadata = item.get("clips_metadata", {})

        additional_info = {
            "is_paid_partnership": item.get("is_paid_partnership", False),
            "can_viewer_reshare": item.get("can_viewer_reshare", False),
            "comments_disabled": item.get("comments_disabled", False),
            "social_context": item.get("social_context"),
            "fb_like_count": item.get("fb_like_count"),
        }

        return {
            "success": True,
            "data": {
                "reel_info": reel_info,
                "user": user_info,
                "video_urls": video_urls,
                "thumbnail_urls": thumbnail_urls,
                "audio_url": audio_url,
                "clips_metadata": clips_metadata,
                **additional_info,
            },
        }

    except Exception as exc:  # pragma: no cover - depends on upstream payload shape
        return {"error": f"Failed to extract data: {exc}"}


def scrape_instagram_reel(url: str) -> dict:
    shortcode = extract_shortcode_from_url(url)
    payload = create_payload(shortcode)

    try:
        response = requests.post(
            "https://www.instagram.com/graphql/query",
            headers=_DEFAULT_HEADERS,
            data=payload,
            timeout=10,
        )
    except requests.Timeout:
        return {"error": "Request timeout"}
    except Exception as exc:
        return {"error": str(exc)}

    if response.status_code == 429:
        return {"error": "Rate limited. Try again later."}
    if response.status_code == 404:
        return {"error": "Reel not found or private."}

    if response.status_code == 200:
        try:
            data = response.json()
        except json.JSONDecodeError:
            return {"error": "Instagram returned invalid JSON"}
        return extract_reel_data(data)

    return {"error": f"Unexpected status: {response.status_code}"}


@app.post("/reel-info")
def get_reel_info():
    try:
        payload = request.get_json(silent=True) or {}
        url = payload.get("url")
        if not url:
            return jsonify({"error": "Missing 'url' in request body"}), 400

        result = scrape_instagram_reel(url)
        status = 200 if result.get("success") else 400
        return jsonify(result), status
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:  # pragma: no cover - generic defensive block
        return jsonify({"error": f"Internal server error: {exc}"}), 500

