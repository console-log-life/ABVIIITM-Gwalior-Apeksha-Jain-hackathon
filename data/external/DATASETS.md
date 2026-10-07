# External datasets

Downloaded by `src/scripts/datasets/prepare_public.py` with the Hugging Face `datasets` library. The data itself is git-ignored; the split ids (with sha256 checksums) are committed in `data/splits/` so the training notebook rebuilds exactly the same splits.

**Split rule (seed 42):** test = the dataset's own `validation` split, held out and used only for the final evaluation; train rows that duplicate a test row (same text after removing links) or nearly duplicate one (rapidfuzz ratio >= 92) are removed from train; dev = a stratified 10% of the rest.

**Financial PhraseBank is NOT used** to evaluate FinBERT: ProsusAI/finbert was trained on it.

## zeroshot/twitter-financial-news-sentiment

- Source: https://huggingface.co/datasets/zeroshot/twitter-financial-news-sentiment (revision `ccbe24de388e287beb92dd393a335c376b350ac3`)
- Licence: MIT (dataset card: 'released under the MIT License')
- Text: English finance-related tweets (Twitter API), human-annotated.
- Rows on the hub: train 9543, validation 2388
- Leakage removed from train: **227** rows (duplicates/near-duplicates of test rows)
- Our splits: train **8384**, dev **932**, test **2388** (sha256 `699f27480afdf567…`)
- Dataset labels (3): Bearish, Bullish, Neutral
- Mapping to our labels: Bearish → Negative; Bullish → Positive; Neutral → Neutral
- Test label distribution (ours): {'Neutral': 1566, 'Positive': 475, 'Negative': 347}
- Used for: fine-tuning FinBERT sentiment and comparing base vs fine-tuned on the held-out test

## zeroshot/twitter-financial-news-topic

- Source: https://huggingface.co/datasets/zeroshot/twitter-financial-news-topic (revision `acbc8af2a35ccf0916124efcbe9e6cf25f191012`)
- Licence: MIT (dataset card: 'released under the MIT License')
- Text: English finance-related tweets (Twitter API), human-annotated.
- Rows on the hub: train 16990, validation 4117
- Leakage removed from train: **1270** rows (duplicates/near-duplicates of test rows)
- Our splits: train **14149**, dev **1571**, test **4117** (sha256 `17c077234ad22d0d…`)
- Dataset labels (20): Analyst Update, Fed | Central Banks, Company | Product News, Treasuries | Corporate Debt, Dividend, Earnings, Energy | Oil, Financials, Currencies, General News | Opinion, Gold | Metals | Materials, IPO, Legal | Regulation, M&A | Investments, Macro, Markets, Politics, Personnel Change, Stock Commentary, Stock Movement
- Mapping to our labels: Analyst Update → Other; Fed | Central Banks → Macroeconomic; Company | Product News → Product Launch; Treasuries | Corporate Debt → Credit Event; Dividend → Earnings; Earnings → Earnings; Energy | Oil → Macroeconomic; Financials → Other; Currencies → Macroeconomic; General News | Opinion → Other; Gold | Metals | Materials → Macroeconomic; IPO → Other; Legal | Regulation → Regulatory; M&A | Investments → M&A; Macro → Macroeconomic; Markets → Other; Politics → Geopolitical; Personnel Change → Management; Stock Commentary → Other; Stock Movement → Other
- Test label distribution (ours): {'Other': 1433, 'Product Launch': 852, 'Macroeconomic': 820, 'Earnings': 339, 'Geopolitical': 249, 'Regulatory': 119, 'M&A': 116, 'Management': 112, 'Credit Event': 77}
- Used for: training the learned event classifier (hybrid with the rules) and comparing it with the rule engine on the held-out test

## Considered and skipped

- **SEntFiN 1.0** (Indian financial news headlines, entity-level sentiment): the official copy is on Kaggle (`ankurzing/aspect-based-sentiment-analysis-for-financial-news`), which needs a logged-in Kaggle API token that this machine does not have. The only Hugging Face copy found (`temetnosce01/phrasebank_and_sentfin`) is a third-party mix with Financial PhraseBank and no clear licence, so it was not used. It can be added later if downloaded manually with its licence recorded.
- **EDT** (corporate event detection, github.com/Zhihan1996/TradeTheEvent): hosted on Google Drive; the repository states no licence (GitHub reports none), and only 2 of its 11 event types (Acquisition, dividends) map to ours. Skipped because the licence is unclear.
