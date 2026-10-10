"""Translate a fixed, already grounded quote without asking the model to copy it again."""
from pydantic import Field

from .source_analysis import QUOTE_CHARS, Schema


class KoreanTranslation(Schema):
    claim_index: int = Field(ge=1, le=12, strict=True)
    korean_text: str = Field(min_length=1, max_length=QUOTE_CHARS,
                            pattern=r'[\s\S]*[가-힣][\s\S]*')


class KoreanTranslations(Schema):
    translations: list[KoreanTranslation] = Field(min_length=1, max_length=12)
