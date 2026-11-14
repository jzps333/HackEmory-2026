# Payment demo scripts (devnet only)

ScanSafe's `POST /pay` sends real transactions, but only on Solana **devnet** (test SOL with no
value). Before it signs anything the server:

- refuses any `SOLANA_RPC_URL` that isn't `https://` with `devnet` (and not `mainnet`) in the host,
- asks the RPC for its genesis hash and refuses unless it is devnet's
  (`EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG`), so a mainnet endpoint never works whatever its name,
- refuses amounts over 0.05 SOL (demo codes ask for 0.01 and 0.005),
- refuses unless the user approved (`approved: true`) and the QR's label + wallet match
  `KNOWN_MERCHANTS` in `api/merchants.py` (it never trusts the client's `merchant_verified`).

Every business here is made up (Peachtree Parking Co., Magnolia Diner).

## What is set up on the API server (root@144.202.25.65)

Keypairs (Solana CLI JSON format, made with `solders`, `chmod 600`, never in git, never printed):

| File | Role | Public address |
|---|---|---|
| `/root/solana/devnet-payer.json` | payer (the "customer"; `/pay` spends from it) | `DyFY4o9utLvfwAg7Nep246iM1Jd3trCRjBUrZvmavkk9` |
| `/root/solana/merchant-peachtree.json` | Peachtree Parking Co. | `6jQGteA52iYssC8A8ss3tsnfGtPCAGPaDH5Z1o8X66TL` |
| `/root/solana/merchant-magnolia.json` | Magnolia Diner | `9qAFfuxQcEsTwPirRu24BGh7UzKeJA5ayXKghufTDqXX` |

Only the public addresses are in code (`api/merchants.py`). The merchant keypairs are only kept so
we could move their test SOL back to the payer later.

`~/HackEmory-2026/.env` (chmod 600) has:

```
SOLANA_RPC_URL=https://api.devnet.solana.com
SOLANA_KEYPAIR_PATH=/root/solana/devnet-payer.json
```

## Top up devnet SOL

The devnet RPC faucet (`requestAirdrop`, `solana airdrop`) is closed ("The RPC faucet is closed on
this cluster"). Use the web faucet:

1. Open https://faucet.solana.com, choose **devnet**.
2. Paste the payer's public address `DyFY4o9utLvfwAg7Nep246iM1Jd3trCRjBUrZvmavkk9`, request 1-5 SOL.
3. Check balances (prints public addresses and balances only):

```bash
ssh root@144.202.25.65 'cd ~/HackEmory-2026 && python3 scripts/devnet_wallets.py'
```

When the payer is empty, `/pay` answers `503 payer_unfunded`.

## Regenerate the QR codes

Run after changing `api/merchants.py` (the codes embed the wallet address):

```bash
python3 scripts/make_demo_qr.py                     # random scammer wallet
python3 scripts/make_demo_qr.py --scammer <address> # or a specific "scammer" address
```

It writes, and prints the Solana Pay URL of each (`solana:<wallet>?amount=&reference=&label=&message=`,
fresh `reference` key every run):

| File | Pays | Expected |
|---|---|---|
| `fixtures/qr/real_meter.png` | Peachtree Parking Co., 0.01 SOL, "Meter 42" | safe, payable |
| `fixtures/qr/magnolia_table.png` | Magnolia Diner, 0.005 SOL, "Table 7" | safe, payable |
| `fixtures/qr/fake_sticker.png` | an unknown wallet, same label/amount/message as `real_meter` | malicious (impersonation), `/pay` refuses |

## Try it end to end

```bash
python3 scripts/devnet_e2e.py            # against https://api.scansafe.nyc; pays 0.01 test SOL
python3 scripts/devnet_e2e.py --no-pay   # scans + refusal checks only
```

It decodes each PNG, `POST /scan`s it, checks `/pay` refuses the impostor and an unapproved payment,
then pays `real_meter` exactly like the app (`{scan_id, payment, approved: true}`) and confirms the
transaction (`getSignatureStatuses`, `getTransaction`) and the merchant's balance on devnet. Needs
`opencv-python-headless` (in `requirements.txt`). It prints the explorer link
(`https://explorer.solana.com/tx/<signature>?cluster=devnet`).

By hand:

```bash
curl -s https://api.scansafe.nyc/pay -H 'content-type: application/json' -d '{
  "scan_id": "demo", "approved": true,
  "payment": {"recipient": "6jQGteA52iYssC8A8ss3tsnfGtPCAGPaDH5Z1o8X66TL", "amount_sol": 0.01,
              "label": "Peachtree Parking Co.", "message": "Meter 42"}}'
```

Deploying: copy the changed files to `~/HackEmory-2026` on the server and restart the `api` tmux
session (see HANDOFF.md).

## Detection eval (`eval_detection.py`, not payments)

Labeled URLs live in `eval/labeled_urls.csv` (`scam` = should be malicious or suspicious, `safe` =
should be safe). Each live run is one sequential scan per URL against the shared sandbox, so keep runs
small while the demo is live.

```bash
python3 scripts/eval_detection.py                                 # live: POST https://api.scansafe.nyc/scan
python3 scripts/eval_detection.py --rescore eval/baseline.json -v # offline: this checkout's rule on a saved run
```

`eval/baseline.json` is the run from before `api/signals.py` (33/35). Live runs are saved as
`eval/results-<timestamp>.json` (gitignored).
