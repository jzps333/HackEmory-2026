# Payment demo scripts (devnet only)

ScanSafe's `POST /pay` sends real transactions, but only on Solana **devnet** (test SOL with no
value). The server refuses any `SOLANA_RPC_URL` whose host doesn't contain `devnet`, refuses
amounts over 0.5 SOL, and refuses wallets that don't match `KNOWN_MERCHANTS`.

## 1. Make a devnet payer wallet (the "customer")

```bash
solana-keygen new -o ~/scansafe-devnet.json          # keep this file private, never commit it
solana config set --url devnet
solana airdrop 2 --url devnet --keypair ~/scansafe-devnet.json
solana balance --url devnet --keypair ~/scansafe-devnet.json
```

If the airdrop is rate limited, use https://faucet.solana.com (choose devnet).

Add to your `.env` (never commit `.env`):

```
SOLANA_KEYPAIR_PATH=~/scansafe-devnet.json
SOLANA_RPC_URL=https://api.devnet.solana.com
```

## 2. Make the merchant wallet (Peachtree Parking Co., a made-up demo brand)

```bash
solana-keygen new -o ~/peachtree-merchant.json
solana address --keypair ~/peachtree-merchant.json    # prints the public address
```

Put that public address into `KNOWN_MERCHANTS` in `api/scan.py`:

```python
KNOWN_MERCHANTS: dict[str, str] = {
    "Peachtree Parking Co.": "<merchant public address>",
}
```

Only the public address goes in code. The merchant keypair file is just so you can show the
balance going up: `solana balance <address> --url devnet`.

## 3. Regenerate the QR codes

Run this again after changing `KNOWN_MERCHANTS` (the codes embed the wallet address):

```bash
python3 scripts/make_demo_qr.py                     # random scammer wallet
python3 scripts/make_demo_qr.py --scammer <address> # or a specific "scammer" address
```

It writes `fixtures/qr/real_meter.png` (pays the verified merchant, 0.02 SOL, "Meter 42") and
`fixtures/qr/fake_sticker.png` (same label and amount, different wallet) and prints both URLs.
Each run uses a fresh Solana Pay `reference`.

## 4. Try it

```bash
uvicorn api.main:app --reload
curl -s localhost:8000/pay -H 'content-type: application/json' -d '{
  "scan_id": "demo", "approved": true,
  "payment": {"recipient": "<merchant address>", "amount_sol": 0.02,
              "label": "Peachtree Parking Co.", "message": "Meter 42"}}'
```

The response has `explorer_url` (https://explorer.solana.com/tx/...?cluster=devnet).
