from decimal import Decimal
from types import SimpleNamespace

from app.bot.charts import pressure_bar, sparkline
from app.bot.formatting import candidate_text, coin_scan_block, pump_after_call_block, scan_list_text
from app.bot.report_image import render_report
from app.domain import CoinScan, RiskVerdict
from app.scanner.risk_scan import evaluate_deep_risk
from app.scanner.security import _from_rugcheck, _merge_scans, finalize, parse_spl_mint, top10_from_largest
from app.config import Settings
from app.scanner.degen import DegenRanker
from app.services.analysis import AnalysisService
from app.scanner.filters import FilterEngine
from app.scanner.risk import RiskAnalyzer
from app.scanner.scoring import ScoringEngine
from tests.test_analysis import snapshot


def _analysis(**overrides):
    settings = Settings(_env_file=None)
    service = AnalysisService(FilterEngine(settings), RiskAnalyzer(), ScoringEngine(settings), DegenRanker(settings), settings)
    return service.analyze(snapshot(**overrides))


def test_degen_ranker_keeps_only_the_best_setup():
    settings = Settings(_env_file=None, max_degen_picks=1)
    ranker = DegenRanker(settings)
    elite = _analysis(
        symbol="ELITE",
        price_change_m5=Decimal("6"),
        price_change_1h=Decimal("18"),
        price_change_24h=Decimal("40"),
        market_cap=Decimal("80000"),
        liquidity=Decimal("25000"),
        buys=200,
        sells=80,
        buys_m5=40,
        sells_m5=10,
        pair_age_seconds=600,
    )
    junk = _analysis(symbol="JUNK", price_change_1h=Decimal("-12"), price_change_24h=Decimal("10"), market_cap=Decimal("50000000"), buys=20, sells=90, pair_age_seconds=600)
    picks = ranker.select_best([elite, junk], limit=1)
    assert len(picks) == 1
    assert picks[0].snapshot.symbol == "ELITE"


def test_already_vertical_tokens_are_not_selected():
    exploded = _analysis(price_change_24h=Decimal("400"), price_change_1h=Decimal("80"))
    assert exploded.too_late
    picks = DegenRanker(Settings(_env_file=None)).select_best([exploded], limit=3)
    assert picks == []


def test_sparkline_and_pressure_render():
    tape = sparkline([1, 2, 3, 8, 5])
    assert len(tape) >= 2
    assert set(tape) <= set("▁▂▃▄▅▆▇█")
    assert "🟩" in pressure_bar(80, 20)
    assert pressure_bar(None, 1) == "Data unavailable"


def test_contract_lookup_shows_pump_after_bot_call():
    call = SimpleNamespace(
        id=12,
        status="ACTIVE",
        reference_price=Decimal("1"),
        current_price=Decimal("4.2"),
        current_multiple=Decimal("4.2"),
        highest_multiple=Decimal("6.1"),
        reference_timestamp=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    text = pump_after_call_block([call], Decimal("4.2"))
    assert "4.20X" in text
    assert "+320.00%" in text
    assert "Call #12" in text
    live = _analysis(symbol="PEPE")
    card = candidate_text(live, prior_calls=[call])
    assert "BOT CALLED THIS" in card
    assert "never been called" not in card.lower()
    assert "COOKING" in text or "MOON" in text


def test_lookup_without_history_is_honest():
    text = pump_after_call_block([], Decimal("1"))
    assert "never been called" in text.lower()
    assert "NOT CALLED BY BOT" in text


def test_coin_scan_flags_honeypot_and_open_authorities():
    scan = finalize(CoinScan(honeypot=True, mint_authority=True, freeze_authority=True, buy_tax=Decimal("12"), source="test"))
    assert scan.fatal
    text = coin_scan_block(scan)
    assert "HONEYPOT" in text
    assert "MINT OPEN" in text
    assert "FREEZE OPEN" in text
    clean = finalize(CoinScan(honeypot=False, mint_authority=False, freeze_authority=False, lp_locked=True, ownership_renounced=True, source="test"))
    assert not clean.fatal
    assert "CLEAN" in coin_scan_block(clean)
    live = _analysis(symbol="SCAN")
    live.coin_scan = clean
    assert "COIN SCAN" in candidate_text(live)
    listed = scan_list_text([live], "BEST")
    assert "CLEAN" in listed or "default check" in listed
    png = render_report(live, [1.0, 1.1, 1.05, 1.2])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_fluxrpc_mint_parse_and_top_holders():
    mint = {
        "id": 1,
        "result": {"value": {"data": {"parsed": {"info": {
            "decimals": 6,
            "freezeAuthority": None,
            "mintAuthority": "Dev111111111111111111111111111111111111111",
            "supply": "1000",
        }}}}},
    }
    largest = {
        "id": 2,
        "result": {"value": [
            {"amount": "400"},
            {"amount": "200"},
            {"amount": "50"},
        ]},
    }
    scan = parse_spl_mint(mint)
    assert scan.mint_authority is True
    assert scan.freeze_authority is False
    assert top10_from_largest(mint, largest) == Decimal("65")


def test_rugcheck_uses_total_holders_and_honeypot_from_risks():
    clean = _from_rugcheck({
        "totalHolders": 1842,
        "token": {"mintAuthority": None, "freezeAuthority": None},
        "topHolders": [{"address": "Aaa1111111111111111111111111111111111111111", "pct": 10}, {"address": "Bbb", "pct": 5}],
        "rugged": False,
        "risks": [],
    }, "rugcheck")
    assert clean.holders == 1842
    assert clean.honeypot is False
    assert clean.mint_authority is False
    assert clean.top_holders
    assert clean.top10_percent == Decimal("15")
    honey = _from_rugcheck({
        "totalHolders": 12,
        "token": {},
        "topHolders": [{"address": "x", "pct": 1}],
        "risks": [{"name": "Honeypot risk", "level": "danger"}],
        "rugged": False,
    }, "rugcheck")
    assert honey.honeypot is True
    assert honey.holders == 12


def test_merge_prefers_birdeye_holder_count():
    merged = _merge_scans(
        CoinScan(holders=20, mint_authority=True, source="fluxrpc"),
        CoinScan(holders=1842, source="birdeye"),
    )
    assert merged.holders == 1842
    assert merged.mint_authority is True


def test_silence_when_nothing_clears_the_degen_bar():
    cooked = _analysis(market_cap=Decimal("9000000"), liquidity=Decimal("400000"), price_change_24h=Decimal("400"))
    assert DegenRanker(Settings(_env_file=None)).select_best([cooked]) == []


def test_deep_risk_fail_on_honeypot_and_open_freeze():
    live = _analysis(symbol="TRAP")
    live.coin_scan = CoinScan(honeypot=True, freeze_authority=True, source="test")
    report = evaluate_deep_risk(live)
    assert report.verdict == RiskVerdict.FAIL
    assert any("Honeypot" in item for item in report.critical)
    ranker = DegenRanker(Settings(_env_file=None))
    live.deep_risk = report
    assert ranker.may_call(live) is False


def test_pass_solana_clean_scan_can_official_call():
    live = _analysis(symbol="ELITE")
    live.coin_scan = CoinScan(
        honeypot=False,
        mint_authority=False,
        freeze_authority=False,
        lp_locked=True,
        top10_percent=Decimal("22"),
        holders=800,
        source="test",
    )
    live.deep_risk = evaluate_deep_risk(live)
    live = DegenRanker(Settings(_env_file=None)).apply(live)
    assert live.deep_risk.verdict == RiskVerdict.PASS
    assert live.degen_score >= 78
    assert DegenRanker(Settings(_env_file=None)).may_call(live)


def test_pass_with_warn_needs_85_to_call():
    live = _analysis(symbol="WARN")
    live.coin_scan = CoinScan(honeypot=None, mint_authority=None, freeze_authority=None, source="test")
    live.deep_risk = evaluate_deep_risk(live)
    ranker = DegenRanker(Settings(_env_file=None))
    live = ranker.apply(live)
    if live.deep_risk.verdict == RiskVerdict.PASS_WITH_WARN:
        live.degen_score = 80
        assert ranker.may_call(live) is False
        live.degen_score = 86
        assert ranker.may_call(live) is True


def test_desk_scan_can_show_more_than_one_watch():
    a = _analysis(symbol="ONE")
    b = _analysis(symbol="TWO")
    picks = DegenRanker(Settings(_env_file=None)).select_best([a, b], limit=2)
    assert len(picks) == 2


def test_alert_and_ca_cards_include_risk_verdict():
    from app.bot.formatting import alert_text, candidate_text, deep_risk_block
    live = _analysis(symbol="ELITE")
    live.coin_scan = CoinScan(honeypot=False, mint_authority=False, freeze_authority=False, lp_locked=True, source="test")
    live.deep_risk = evaluate_deep_risk(live)
    text = alert_text(live, 7, "A")
    assert "RISK" in text
    assert "PASS" in text
    assert "WHY THIS ONE" in text
    assert "NFA" in text
    card = candidate_text(live)
    assert "RISK" in card
    assert "PASS" in deep_risk_block(live.deep_risk)
