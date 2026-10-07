# Dashboard verification (2026-10-07 16:46)

`python src/scripts/verify_dashboard.py`: **55/55 steps passed**. Own API + dashboard, headless Microsoft Edge (Playwright), 1440×900; a step fails on any Streamlit exception box, error box, failed expectation or server-log error. Screenshot per step in brackets.

| result | page | step | detail |
|---|---|---|---|
| PASS | Home | open page | [01_home_open_page.jpg] |
| PASS | Home | time machine: drag back | value 1791230625000000 -> 1791209025000000 [02_home_time_machine_drag_back.jpg] |
| PASS | Home | time machine: Latest button | clicked 'Latest' [03_home_time_machine_latest_button.jpg] |
| PASS | Home | auto-refresh on (6 s) | toggled 'Auto-refresh' [04_home_auto_refresh_on_6_s_.jpg] |
| PASS | Home | auto-refresh off | toggled 'Auto-refresh' [05_home_auto_refresh_off.jpg] |
| PASS | Home | mode switch: REPLAY + Apply | clicked 'Apply mode' [06_home_mode_switch_replay_apply.jpg] |
| PASS | Home | after REPLAY finished | [07_home_after_replay_finished.jpg] |
| PASS | Home | ▶ Scenario demo | clicked '▶ Scenario demo' [08_home_scenario_demo.jpg] |
| PASS | Home | after scenario story | [09_home_after_scenario_story.jpg] |
| PASS | Watchlist | open page | [10_watchlist_open_page.jpg] |
| PASS | Watchlist | window selector -> 72 h | chose '72' [11_watchlist_window_selector_72_h.jpg] |
| PASS | Watchlist | show all held issuers | toggled 'Show all held issuers' [12_watchlist_show_all_held_issuers.jpg] |
| PASS | Watchlist | Tata Motors expander open | already expanded (WATCH-NEGATIVE) [13_watchlist_tata_motors_expander_open.jpg] |
| PASS | Watchlist | credit brief toggle | toggled 'Credit brief' [14_watchlist_credit_brief_toggle.jpg] |
| PASS | Watchlist | download credit brief PDF | PDF 2,693 bytes [15_watchlist_download_credit_brief_pdf.jpg] |
| PASS | Watchlist | Explain → link | [16_watchlist_explain_link.jpg] |
| PASS | Explainability | opened from Explain link | [17_explainability_opened_from_explain_link.jpg] |
| PASS | Watchlist | propagated-exposure link (table) | [18_watchlist_propagated_exposure_link_table_.jpg] |
| PASS | Propagation | opened from watchlist link | [19_propagation_opened_from_watchlist_link.jpg] |
| PASS | Propagation | open page | [20_propagation_open_page.jpg] |
| PASS | Propagation | issuer selector | chose 'Tesla Inc. · MONITOR' [21_propagation_issuer_selector.jpg] |
| PASS | Propagation | positions selector | chose 'Ford Motor Co.' [22_propagation_positions_selector.jpg] |
| PASS | Feed | open page | [23_feed_open_page.jpg] |
| PASS | Feed | source type filter (drop one) | tags 2 -> 1 [24_feed_source_type_filter_drop_one_.jpg] |
| PASS | Feed | provenance filter (drop one) | tags 2 -> 1 [25_feed_provenance_filter_drop_one_.jpg] |
| PASS | Feed | source filter (drop one) | tags 1 -> 0 [26_feed_source_filter_drop_one_.jpg] |
| PASS | NLP signals | open page | [27_nlp_signals_open_page.jpg] |
| PASS | NLP signals | risk level pills (deselect Low) | [28_nlp_signals_risk_level_pills_deselect_low_.jpg] |
| PASS | NLP signals | event type selector | chose 'Credit Event' [29_nlp_signals_event_type_selector.jpg] |
| PASS | NLP signals | event type back to All | chose 'All' [30_nlp_signals_event_type_back_to_all.jpg] |
| PASS | NLP signals | minimum impact slider | value 1 -> 3 [31_nlp_signals_minimum_impact_slider.jpg] |
| PASS | NLP signals | ticker trend multiselect | tags 4 -> 3 [32_nlp_signals_ticker_trend_multiselect.jpg] |
| PASS | Portfolio | open page | [33_portfolio_open_page.jpg] |
| PASS | Stress Test | open page | [34_stress_test_open_page.jpg] |
| PASS | Stress Test | stress run selector | chose '2026-10-07 11:10 UTC · geopolitical_moderate · 1.3' [35_stress_test_stress_run_selector.jpg] |
| PASS | Stress Test | tab By sector | [36_stress_test_tab_by_sector.jpg] |
| PASS | Stress Test | tab By country | [37_stress_test_tab_by_country.jpg] |
| PASS | Stress Test | tab Shocks applied | [38_stress_test_tab_shocks_applied.jpg] |
| PASS | Stress Test | tab By issuer | [39_stress_test_tab_by_issuer.jpg] |
| PASS | Stress Test | what-if: start from | chose 'Geopolitical shock (moderate)' [40_stress_test_what_if_start_from.jpg] |
| PASS | Stress Test | what-if: HY spread slider | value 150 -> 200 [41_stress_test_what_if_hy_spread_slider.jpg] |
| PASS | Stress Test | what-if: compare toggle | toggled 'Compare with' [42_stress_test_what_if_compare_toggle.jpg] |
| PASS | Stress Test | manual: scenario selector | chose 'Geopolitical shock (severe) (geopolitical_severe)' [43_stress_test_manual_scenario_selector.jpg] |
| PASS | Stress Test | manual: idiosyncratic scenario | [44_stress_test_manual_idiosyncratic_scenario.jpg] |
| PASS | Stress Test | manual: issuer selector | chose 'Amazon.com Inc. (US-AMZN)' [45_stress_test_manual_issuer_selector.jpg] |
| PASS | Stress Test | Run stress test | clicked 'Run stress test' [46_stress_test_run_stress_test.jpg] |
| PASS | Explainability | open page | [47_explainability_open_page.jpg] |
| PASS | Explainability | signal selector | chose '8.3 · MARKET · Macroeconomic · Fed rate hike odds ' [48_explainability_signal_selector.jpg] |
| PASS | Explainability | tab: Analyse your own headline | [49_explainability_tab_analyse_your_own_headline.jpg] |
| PASS | Explainability | Analyse your own headline | submitted [50_explainability_analyse_your_own_headline.jpg] |
| PASS | Source Health | open page | [51_source_health_open_page.jpg] |
| PASS | Home | ⟲ Reset | clicked '⟲ Reset' [52_home_reset.jpg] |
| PASS | Home | after reset | [53_home_after_reset.jpg] |
| PASS | server logs | API log clean | 0 bad lines |
| PASS | server logs | dashboard log clean | 0 bad lines |
