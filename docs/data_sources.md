# Data sources

All data in this project is **public**. None of it is Worthington Enterprises internal data. Raw files are kept out of git (`data/raw/` is gitignored). Check your local copies against the hashes below.

| ID | File | Type | Source | Licence / status | Retrieved | Bytes | SHA-256 |
|---|---|---|---|---|---|---|---|
| DATACO | `data/raw/dataco/DataCoSupplyChainDataset.csv` | Public historical **retail/e-commerce** sample data (not manufacturing, not Worthington) | Mendeley Data, *DataCo Smart Supply Chain for Big Data Analysis*, v5 — https://data.mendeley.com/datasets/8gx2fvg2k6/5 | CC BY 4.0 (attribution required) | 2026-11-25 | 95,910,149 | `fa6d022ed437155e1a2f0378710602848703c8a7f203f7ff5d77805bf8480aa6` |
| DATACO_DICT | `data/raw/dataco/DescriptionDataCoSupplyChain.csv` | Column dictionary | same as above | CC BY 4.0 | 2026-11-25 | 3,444 | `9828e34669bd6d77e3b4463364cc44a5d52446b5e246fc258758cfe592566c4b` |
| DOC_SQAM | `data/raw/documents/supplier-quality-assurance-manual_102325.pdf` | Public supplier quality manual | https://www.worthingtonenterprises.com/docs/default-source/default-document-library/misc.-support-docs/supplier-quality-assurance-manual_102325.pdf | Publicly published by the company | 2026-11-25 | 1,497,410 | `167e660c6eb4f3787deba7661e70594d089aaa8ed7e93e9d5665cb3bf16879b3` |
| DOC_SCOC | `data/raw/documents/supplier-code-of-conduct_06162025.pdf` | Public supplier code of conduct | https://www.worthingtonenterprises.com/docs/default-source/default-document-library/misc.-support-docs/supplier-code-of-conduct_06162025.pdf | Publicly published by the company | 2026-11-25 | 1,165,115 | `bdbba13d91595eadb9f929bcae73c43415c6b706c55a4b23ac00cd00d50addbd` |
| DOC_AR26 | `data/raw/documents/2026_annual_report.pdf` | Public annual report (SEC EDGAR) | https://www.sec.gov/Archives/edgar/data/108516/000119312526348735/2026_annual_report.pdf | Public SEC filing | 2026-11-25 | 1,247,244 | `a02b4433da6daf1486c1e1ee71d11ba8cc192289a35e7bc6e68cc30ec146b68d` |

## How to obtain (reproducible manual download)

Mendeley Data serves the files through a browser download page, so acquisition is a documented manual step rather than scraping. Hashes make it verifiable.

1. Open https://data.mendeley.com/datasets/8gx2fvg2k6/5 and download `DataCoSupplyChainDataset.csv` and `DescriptionDataCoSupplyChain.csv` into `data/raw/dataco/`.
2. Download the three PDFs from the URLs above into `data/raw/documents/`, keeping the original filenames.
3. Verify against `data/manifest.json`:
   ```powershell
   .venv\Scripts\python -m supplychain_copilot.ingestion.download_data
   ```
   The cleaning pipeline refuses to run if the CSV hash doesn't match.

Attribution for DataCo: Constante, Fabian; Silva, Fernando; Pereira, António (2019), "DataCo SMART SUPPLY CHAIN FOR BIG DATA ANALYSIS", Mendeley Data, V5. *(The citation format is to be checked against the Mendeley page in Phase 1.)*

Not used in v1: `tokenized_access_logs.csv` (not needed), FRED HOUST, UCI AI4I (optional extensions).
