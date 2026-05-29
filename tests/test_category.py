"""Tests for src/cse_bot/category.py — 5-category classification + importance."""
from __future__ import annotations

import pytest

from cse_bot.category import (
    CATEGORY_ACADEMIC,
    CATEGORY_ACTIVITY,
    CATEGORY_CAREER,
    CATEGORY_GENERAL,
    CATEGORY_SCHOLARSHIP,
    CLASSIFICATION_PALETTE,
    DEFAULT_COLOR,
    classification_to_color,
    classify,
    extract_category,
    is_important,
)


class TestExtractCategory:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("[장학] 2026.2학기 주거안정장학금 신청 안내(~6.22.)", "장학"),
            ("[수업]2026학년도 여름 계절수업 폐강강좌 통보", "수업"),
            ("[AI융합교육원] 2026 PNU AI Booster 2기 모집", "AI융합교육원"),
            ("[국제협력실] 2026 하계 APRU Certificate", "국제협력실"),
            ("[취업전략과] 2026 GLOBAL TALENT FAIR", "취업전략과"),
            ("[모집] 2026학년도 여름계절학기 현장실습학기제", "모집"),
            ("[ 졸업 ] 2026년 8월 졸업예정자", "졸업"),
        ],
    )
    def test_extracts_raw_prefix(self, title: str, expected: str) -> None:
        assert extract_category(title) == expected

    @pytest.mark.parametrize(
        "title",
        [
            "2026학년도 제2학기 재입학 시행계획 알림",
            "학생 출석인정원 위조 사례 및 징계 조치 증가",
            "디자인테크놀로지전공 소개 자료 공유",
            "",
        ],
    )
    def test_returns_empty_when_no_prefix(self, title: str) -> None:
        assert extract_category(title) == ""


class TestClassify:
    @pytest.mark.parametrize(
        ("title", "category"),
        [
            # Prefix-based
            ("[장학] 2026.2학기 주거안정장학금 신청", CATEGORY_SCHOLARSHIP),
            ("[등록] 2026.1학기 등록금 납부 안내", CATEGORY_SCHOLARSHIP),
            ("[수업] 여름 계절수업 폐강 통보", CATEGORY_ACADEMIC),
            ("[학적] 휴복학 신청 안내", CATEGORY_ACADEMIC),
            ("[입학처] 2026 신입생 입학식", CATEGORY_ACADEMIC),
            ("[졸업] 2026.8 졸업예정자 졸업요건 서류", CATEGORY_CAREER),
            ("[취업전략과] GLOBAL TALENT FAIR", CATEGORY_CAREER),
            ("[대학일자리플러스센터] 채용 멘토링", CATEGORY_CAREER),
            ("[AI융합교육원] AI Booster 2기 모집", CATEGORY_ACTIVITY),
            ("[SW중심대학] PNUPC 경진대회", CATEGORY_ACTIVITY),
            ("[국립대학육성사업] Arise PNU 신청", CATEGORY_ACTIVITY),
            ("[공학교육혁신센터] 캡스톤 디자인 발표회", CATEGORY_ACTIVITY),
            ("[모집] 현장실습학기제 참여학생 모집", CATEGORY_ACTIVITY),
        ],
    )
    def test_prefix_classification(self, title: str, category: str) -> None:
        assert classify(title) == category

    @pytest.mark.parametrize(
        ("title", "category"),
        [
            # Keyword fallback (no prefix)
            ("2026학년도 2학기 수강신청 안내", CATEGORY_ACADEMIC),
            ("여름 계절수업 폐강 강좌 통보", CATEGORY_ACADEMIC),
            ("2026 학위수여식 안내", CATEGORY_ACADEMIC),
            ("2026 정보컴퓨터공학부 신입생 오리엔테이션", CATEGORY_GENERAL),
            ("삼성물산 현직자 온라인 멘토링 신청", CATEGORY_CAREER),
            ("TOPCIT 정기 평가 안내", CATEGORY_CAREER),
            ("프로그래밍 경진대회 참가자 모집", CATEGORY_ACTIVITY),
            ("동아리 신규 회원 모집 안내", CATEGORY_ACTIVITY),
            ("교내 근로봉사 장학생 추가 모집", CATEGORY_SCHOLARSHIP),
        ],
    )
    def test_keyword_fallback(self, title: str, category: str) -> None:
        assert classify(title) == category

    @pytest.mark.parametrize(
        "title",
        [
            "IT관 학부생 공간 안내",
            "학생지원시스템 개인정보 확인 안내",
            "타과생의 부전공 신청에 관한 안내",
            "",
        ],
    )
    def test_falls_back_to_general(self, title: str) -> None:
        assert classify(title) == CATEGORY_GENERAL


class TestIsImportant:
    @pytest.mark.parametrize(
        "title",
        [
            "2026학년도 2학기 수강신청 안내",
            "여름 계절수업 수강정정 기간 안내",
            "[장학] 2026-2학기 국가장학금 1차 신청",
            "[장학] 2026.2학기 주거안정장학금 신청 안내",
            "TOPCIT 정기 평가 응시 안내",
            "PNUPC 프로그래밍 경진대회 참가자 모집",
            "[AI융합교육원] 2026 PNU AI Booster 2기 모집",
            "여름계절학기 AI 부트캠프 참가자 모집",
            "[취업] GLOBAL TALENT 채용박람회 신청",
            "[졸업] 영어인증제 졸업요건 안내",
            "2026.1학기 등록금 납부 안내",
        ],
    )
    def test_flags_important_deadlines(self, title: str) -> None:
        assert is_important(title) is True

    @pytest.mark.parametrize(
        "title",
        [
            "IT관 학부생 공간 안내",
            "타과생의 부전공 신청에 관한 안내",
            "[수업] 효원브릿지 교과목 운영 안내",
            "학생지원시스템 개인정보 확인",
            "디자인테크놀로지전공 소개 자료 공유",
            "",
        ],
    )
    def test_ignores_non_important(self, title: str) -> None:
        assert is_important(title) is False


class TestClassificationToColor:
    @pytest.mark.parametrize(
        ("category", "rgb"),
        [
            (CATEGORY_SCHOLARSHIP, (139, 92, 246)),
            (CATEGORY_ACADEMIC, (20, 184, 166)),
            (CATEGORY_CAREER, (236, 72, 153)),
            (CATEGORY_ACTIVITY, (245, 158, 11)),
            (CATEGORY_GENERAL, (107, 114, 128)),
        ],
    )
    def test_known_categories(self, category: str, rgb: tuple[int, int, int]) -> None:
        assert classification_to_color(category) == rgb

    def test_unknown_returns_default(self) -> None:
        assert classification_to_color("이상한카테고리") == DEFAULT_COLOR

    def test_palette_covers_all_categories(self) -> None:
        for cat in (
            CATEGORY_SCHOLARSHIP, CATEGORY_ACADEMIC, CATEGORY_CAREER,
            CATEGORY_ACTIVITY, CATEGORY_GENERAL,
        ):
            assert cat in CLASSIFICATION_PALETTE
