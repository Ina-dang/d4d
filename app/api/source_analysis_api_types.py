"""수집·분석 API의 파일 경로 ID 제한."""

from typing import Annotated

from fastapi import Path

CollectionId = Annotated[str, Path(pattern=r'^[a-zA-Z0-9_-]{1,80}$')]
