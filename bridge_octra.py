#!/usr/bin/env python3
"""
Octra -> Ethereum Bridge (interactive)
Install: pip install web3 requests eth-abi pynacl
Run:     python3 octra_bridge.py
"""

import base64, hashlib, json, time, sys
from decimal import Decimal, ROUND_DOWN

import requests
from eth_abi import encode
from nacl.signing import SigningKey
from web3 import Web3

OCTRA_RPC    = "https://octrascan.io/rpc"
ETH_RPC      = "https://eth.drpc.org"
VAULT        = "oct5MrNfjiXFNRDLwsodn8Zm9hDKNGAYt3eQDCQ52bSpCHq"
ETH_BRIDGE   = Web3.to_checksum_address("0xE7eD69b852fd2a1406080B26A37e8E04e7dA4caE")
LIGHT_CLIENT = Web3.to_checksum_address("0xC01cA57dc7f7C4B6f1B6b87B85D79e5ddf0dF55d")
DECIMALS     = 6
FEE_RAW      = 1000

BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
ZERO32 = b"\x00" * 32
L_MSG  = b"octra:bridge_message:v1\x00"
L_LEAF = b"octra:bridge_leaf:v1\x00"
L_NODE = b"octra:bridge_node:v1\x00"
MSG_TYPES = ["uint8","uint8","uint64","uint64","bytes32","bytes32","bytes32","address","uint128","uint64"]

BRIDGE_ABI = [
    {"inputs":[],"name":"BRIDGE_VERSION","outputs":[{"type":"uint8"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"DIRECTION_O2E","outputs":[{"type":"uint8"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"OCTRA_CHAIN_ID","outputs":[{"type":"uint64"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"ETH_CHAIN_ID","outputs":[{"type":"uint64"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"SRC_BRIDGE_ID","outputs":[{"type":"bytes32"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"DST_BRIDGE_ID","outputs":[{"type":"bytes32"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"TOKEN_ID_OCT","outputs":[{"type":"bytes32"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"paused","outputs":[{"type":"bool"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"type":"bytes32"}],"name":"processedMessages","outputs":[{"type":"bool"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"components":[{"type":"uint8"},{"type":"uint8"},{"type":"uint64"},{"type":"uint64"},
        {"type":"bytes32"},{"type":"bytes32"},{"type":"bytes32"},{"type":"address"},
        {"type":"uint128"},{"type":"uint64"}],"name":"m","type":"tuple"}],
        "name":"hashBridgeMessage","outputs":[{"type":"bytes32"}],"stateMutability":"pure","type":"function"},
    {"inputs":[{"type":"uint64"},{"components":[{"type":"uint8"},{"type":"uint8"},{"type":"uint64"},
        {"type":"uint64"},{"type":"bytes32"},{"type":"bytes32"},{"type":"bytes32"},{"type":"address"},
        {"type":"uint128"},{"type":"uint64"}],"name":"m","type":"tuple"},
        {"type":"bytes32[]"},{"type":"uint32"}],
        "name":"verifyAndMint","outputs":[{"type":"bytes32"}],"stateMutability":"nonpayable","type":"function"},
    {"anonymous":False,"inputs":[{"indexed":True,"name":"messageId","type":"bytes32"},
        {"indexed":True,"name":"epochId","type":"uint64"},{"indexed":True,"name":"recipient","type":"address"},
        {"indexed":False,"name":"amount","type":"uint256"}],"name":"MintFinalized","type":"event"},
]

LC_ABI = [
    {"inputs":[{"type":"uint64"}],"name":"bridgeRootOf","outputs":[{"type":"bytes32"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"latestEpoch","outputs":[{"type":"uint64"}],"stateMutability":"view","type":"function"},
]

def die(msg):  print(f"\n[ERROR] {msg}"); sys.exit(1)
def ok(msg):   print(f"  [OK] {msg}")
def info(msg): print(f"  ... {msg}")

def to_oct(raw): return str((Decimal(raw) / 10**DECIMALS).quantize(Decimal("0.000001"), rounding=ROUND_DOWN))

def to_raw(amt):
    d = Decimal(str(amt).strip())
    if d <= 0: die("Amount must be > 0")
    r = d * 10**DECIMALS
    if r != r.to_integral_value(): die("Max 6 decimal places")
    return int(r)

def b58enc(data):
    n, out = int.from_bytes(data, "big"), ""
    while n: n, r = divmod(n, 58); out = BASE58[r] + out
    return "1" * sum(1 for b in data if b == 0) + (out or "1")

def octra_address(pub):
    return "oct" + b58enc(hashlib.sha256(pub).digest()).rjust(44, "1")

def rpc(method, params):
    r = requests.post(OCTRA_RPC, json={"jsonrpc":"2.0","id":1,"method":method,"params":params}, timeout=30)
    d = r.json()
    if d.get("error"): raise RuntimeError(f"RPC {method}: {d['error']}")
    return d["result"]

def sha256p(label, data): return hashlib.sha256(label + data).digest()
def hash_leaf(msg):  return sha256p(L_LEAF, encode(MSG_TYPES, list(msg)))
def hash_msg(msg):   return sha256p(L_MSG,  encode(MSG_TYPES, list(msg)))
def hash_node(l, r): return sha256p(L_NODE, l + r)

def build_proof(leaves, idx, dup_last=False):
    layer, i, siblings = list(leaves), idx, []
    while len(layer) > 1:
        nxt = []
        for j in range(0, len(layer), 2):
            if j+1 >= len(layer):
                if dup_last:
                    nxt.append(hash_node(layer[j], layer[j]))
                    if i == j: siblings.append(layer[j]); i = len(nxt)-1
                else:
                    nxt.append(layer[j])
                    if i == j: i = len(nxt)-1
            else:
                nxt.append(hash_node(layer[j], layer[j+1]))
                if   i == j:   siblings.append(layer[j+1]); i = len(nxt)-1
                elif i == j+1: siblings.append(layer[j]);   i = len(nxt)-1
        layer = nxt
    return layer[0], siblings

def fee_params(w3):
    bf  = w3.eth.get_block("latest").get("baseFeePerGas", int(w3.to_wei(1, "gwei")))
    pf  = int(w3.to_wei(0.0001, "gwei"))
    return {"maxPriorityFeePerGas": pf, "maxFeePerGas": int(bf * 1.5) + pf}

# ── Core functions ────────────────────────────────────────────────────────────
def load_account(b64key):
    sk  = SigningKey(base64.b64decode(b64key)[:32])
    pub = bytes(sk.verify_key)
    return {"sk": sk, "pub_b64": base64.b64encode(pub).decode(), "addr": octra_address(pub)}

def get_state(addr):
    d = rpc("octra_balance", [addr])
    nonce = int(d.get("pending_nonce", d.get("nonce", 0)))
    bal   = int(d.get("balance_raw") or to_raw(d.get("balance", "0")))
    return nonce, bal

def json_escape(s): return json.dumps(s, ensure_ascii=False)[1:-1]

def lock_oct(account, evm_addr, amount_raw, nonce):
    ts        = time.time()
    evm_chk   = Web3.to_checksum_address(evm_addr)
    msg_value = json.dumps  ([evm_chk], separators=(",", ":"))
    body = (
        f'{{"from":"{json_escape(account["addr"])}"'
        f',"to_":"{json_escape(VAULT)}"'
        f',"amount":"{json_escape(str(amount_raw))}"'
        f',"nonce":{nonce+1}'
        f',"ou":"{json_escape(str(FEE_RAW))}"'
        f',"timestamp":{json.dumps(float(ts), separators=(",", ":"))}'
        f',"op_type":"call"'
        f',"encrypted_data":"lock_to_eth"'
        f',"message":"{json_escape(msg_value)}"'
        f'}}'
    ).encode()
    sig = account["sk"].sign(body).signature
    payload = {
        "from": account["addr"], "to_": VAULT, "amount": str(amount_raw),
        "nonce": nonce+1, "ou": str(FEE_RAW), "timestamp": ts,
        "signature": base64.b64encode(sig).decode(), "public_key": account["pub_b64"],
        "op_type": "call", "encrypted_data": "lock_to_eth", "message": msg_value,
    }
    res = rpc("octra_submit", [payload])
    return ((res or {}).get("tx_hash") or hashlib.sha256(body).hexdigest()).lower().removeprefix("0x")

def wait_receipt(tx_hash, timeout=300, poll=10):
    deadline, attempt = time.time() + timeout, 0
    while time.time() < deadline:
        attempt += 1
        elapsed = int(time.time() - (deadline - timeout))
        print(f"  ... attempt {attempt} ({elapsed}s elapsed)", end="\r")
        try:
            r = rpc("contract_receipt", [tx_hash])
            if isinstance(r, dict) and r.get("method") == "lock_to_eth":
                if not r.get("success"):
                    die("Lock tx was rejected on-chain (success=false)")
                for ev in r.get("events", []):
                    if ev.get("event") == "Locked":
                        v = ev["values"]
                        print()
                        return {"recipient": v[2], "amount_raw": int(v[1]),
                                "src_nonce": int(v[3]), "epoch": int(r["epoch"])}
        except Exception as e:
            if "not found" not in str(e).lower() and "112" not in str(e):
                print(f"\n  [WARN] {e}")
        time.sleep(poll)
    print()
    die(f"Timeout ({timeout}s) — TX may still confirm later\n"
        f"  Retry: python3 octra_bridge.py --resume {tx_hash}")

def build_message(consts, receipt):
    return (consts["ver"], consts["dir"], consts["src_chain"], consts["dst_chain"],
            consts["src_id"], consts["dst_id"], consts["token_id"],
            Web3.to_checksum_address(receipt["recipient"]),
            int(receipt["amount_raw"]), int(receipt["src_nonce"]))

def get_epoch_messages(epoch, consts):
    msgs, offset = [], 0
    while True:
        page = rpc("octra_transactionsByEpoch", [epoch, 100, offset])
        txs  = (page or {}).get("transactions", [])
        for tx in txs:
            if tx.get("to") != VAULT or tx.get("encrypted_data") != "lock_to_eth": continue
            try:
                r = rpc("contract_receipt", [tx["hash"]])
                for ev in (r or {}).get("events", []):
                    if ev.get("event") != "Locked": continue
                    v   = ev["values"]
                    rec = {"recipient": v[2], "amount_raw": int(v[1]), "src_nonce": int(v[3])}
                    msg = build_message(consts, rec)
                    msgs.append({"tx_hash": tx["hash"], "leaf": hash_leaf(msg),
                                 "msg": msg, "src_nonce": int(v[3])})
            except Exception:
                pass
        if not (page or {}).get("has_more") or len(txs) < 100: break
        offset += len(txs)
    return msgs

def find_proof(epoch_msgs, target_hash, expected_root):
    orders = [
        lambda x: x,
        lambda x: sorted(x, key=lambda r: r["src_nonce"]),
        lambda x: sorted(x, key=lambda r: (r["src_nonce"], r["tx_hash"])),
        lambda x: sorted(x, key=lambda r: r["tx_hash"]),
    ]
    for order in orders:
        rows   = order(list(epoch_msgs))
        leaves = [r["leaf"] for r in rows]
        idx    = next((i for i,r in enumerate(rows) if r["tx_hash"] == target_hash), None)
        if idx is None: continue
        for dup in (False, True):
            root, siblings = build_proof(leaves, idx, dup)
            if root == expected_root:
                return idx, siblings
    die("Cannot build a valid Merkle proof")

def claim_woct(w3, bridge, eth_key, epoch, message, siblings, leaf_idx):
    from web3.exceptions import TimeExhausted
    acct = w3.eth.account.from_key(eth_key)

    siblings_bytes = [s if isinstance(s, bytes) else bytes.fromhex(s.removeprefix("0x"))
                      for s in siblings]
    siblings_bytes = [s.rjust(32, b"\x00") for s in siblings_bytes]

    eth_balance = w3.eth.get_balance(acct.address)
    ok(f"ETH balance: {Web3.from_wei(eth_balance, 'ether'):.6f} ETH  ({acct.address})")
    if eth_balance == 0:
        die("ETH wallet has 0 ETH — need ETH to pay gas for verifyAndMint()")

    call = bridge.functions.verifyAndMint(epoch, message, siblings_bytes, leaf_idx)

    info(f"epoch={epoch}  leaf_idx={leaf_idx}  siblings={len(siblings_bytes)}")

    info("Simulating verifyAndMint()...")
    try:
        gas = int(call.estimate_gas({"from": acct.address}) * 1.05)
        ok(f"Simulation OK — estimated gas: {int(gas / 1.2):,}")
    except Exception as e:
        die(f"Simulation failed (tx would revert): {e}\n"
            f"  Possible causes:\n"
            f"    - Bridge header not yet verified on Ethereum\n"
            f"    - Message already claimed (processedMessages = true)\n"
            f"    - Merkle proof is invalid\n"
            f"    - Bridge is paused")

    fp = fee_params(w3)
    max_fee = fp.get("maxFeePerGas", fp.get("gasPrice", 0))
    est_cost = Web3.from_wei(gas * max_fee, "ether")
    info(f"Estimated cost: ~{est_cost:.6f} ETH  (maxFeePerGas={Web3.from_wei(max_fee,'gwei'):.2f} gwei)")
    if eth_balance < gas * max_fee:
        die(f"Insufficient ETH for gas: need ~{est_cost:.6f} ETH, have {Web3.from_wei(eth_balance,'ether'):.6f} ETH")

    params = {"from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address),
              "gas": gas, "chainId": w3.eth.chain_id, **fp}
    signed     = acct.sign_transaction(call.build_transaction(params))
    tx_hash    = w3.eth.send_raw_transaction(signed.raw_transaction)
    eth_tx_hex = Web3.to_hex(tx_hash)
    info(f"TX submitted: {eth_tx_hex}")
    info(f"Track: https://etherscan.io/tx/{eth_tx_hex}")
    try:
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=600)
        return eth_tx_hex, int(receipt.status)
    except TimeExhausted:
        print(f"\n  [WARN] TX not confirmed after 600s — still pending in mempool")
        print(f"  Track on Etherscan: https://etherscan.io/tx/{eth_tx_hex}")
        print(f"  Do NOT re-run — the tx may still confirm.")
        sys.exit(2)

def main():
    print("=" * 55)
    print("  Octra -> Ethereum Bridge")
    print("=" * 55)

    resume_tx = None
    if "--resume" in sys.argv:
        idx = sys.argv.index("--resume")
        if idx + 1 < len(sys.argv):
            resume_tx = sys.argv[idx + 1].lower().removeprefix("0x")
            print(f"\n[RESUME] TX: {resume_tx}")

    eth_key = input("\nEthereum private key (0x):   ").strip()
    if not eth_key.startswith("0x") or len(eth_key) != 66: die("ETH key must be 0x + 64 hex chars")

    if resume_tx:
        print("\n[1/6] Skipping account load (resume mode)")
        print("[2/6] Skipping balance check (resume mode)")
        print("\n[4/6] Waiting for lock receipt...")
        receipt = wait_receipt(resume_tx)
        ok(f"Locked {to_oct(receipt['amount_raw'])} OCT  |  epoch {receipt['epoch']}  |  nonce {receipt['src_nonce']}")
        tx_hash = resume_tx
    else:
        octra_key = input("Octra private key (base64): ").strip()
        eth_addr  = input("Ethereum recipient address:  ").strip()
        if not Web3.is_address(eth_addr): die("Invalid Ethereum address")

        print("\n[1/6] Loading Octra account...")
        try:    account = load_account(octra_key)
        except: die("Invalid Octra private key (must be base64)")
        ok(f"Address: {account['addr']}")

        print("\n[2/6] Fetching balance...")
        nonce, bal_raw = get_state(account["addr"])
        spendable = bal_raw - FEE_RAW
        ok(f"Balance:   {to_oct(bal_raw)} OCT")
        info(f"Fee:       {to_oct(FEE_RAW)} OCT")
        ok(f"Spendable: {to_oct(spendable)} OCT")
        if spendable <= 0: die("Insufficient balance")

        print()
        amount_raw = to_raw(input(f"Amount to bridge (max {to_oct(spendable)}): "))
        if amount_raw > spendable: die("Amount exceeds spendable balance")
        print(f"\n  Bridge {to_oct(amount_raw)} OCT  ->  {eth_addr}")
        if input("  Confirm? [y/N]: ").strip().lower() != "y":
            print("Cancelled."); sys.exit(0)

        print("\n[3/6] Locking OCT on Octra...")
        tx_hash = lock_oct(account, eth_addr, amount_raw, nonce)
        ok(f"TX: {tx_hash}")

        print("\n[4/6] Waiting for lock receipt...")
        receipt = wait_receipt(tx_hash)
        ok(f"Locked {to_oct(receipt['amount_raw'])} OCT  |  epoch {receipt['epoch']}  |  nonce {receipt['src_nonce']}")

    print("\n[5/6] Connecting to Ethereum...")
    w3 = Web3(Web3.HTTPProvider(ETH_RPC))
    if not w3.is_connected(): die("Cannot connect to Ethereum RPC")
    bridge = w3.eth.contract(address=ETH_BRIDGE, abi=BRIDGE_ABI)
    lc     = w3.eth.contract(address=LIGHT_CLIENT, abi=LC_ABI)
    if bridge.functions.paused().call(): die("Bridge is currently paused")

    consts = {
        "ver":       bridge.functions.BRIDGE_VERSION().call(),
        "dir":       bridge.functions.DIRECTION_O2E().call(),
        "src_chain": bridge.functions.OCTRA_CHAIN_ID().call(),
        "dst_chain": bridge.functions.ETH_CHAIN_ID().call(),
        "src_id":    bytes(bridge.functions.SRC_BRIDGE_ID().call()),
        "dst_id":    bytes(bridge.functions.DST_BRIDGE_ID().call()),
        "token_id":  bytes(bridge.functions.TOKEN_ID_OCT().call()),
    }
    message    = build_message(consts, receipt)
    message_id = hash_msg(message)
    if bridge.functions.processedMessages(message_id).call(): die("Already claimed")
    ok("Bridge contract OK")

    print("\n[6/6] Waiting for bridge header on Ethereum...")
    deadline, bridge_root = time.time() + 1800, ZERO32
    while time.time() < deadline:
        bridge_root = bytes(lc.functions.bridgeRootOf(receipt["epoch"]).call())
        if bridge_root != ZERO32: break
        info("header not yet available, retrying in 15s")
        time.sleep(15)
    if bridge_root == ZERO32: die("Bridge header not available after 30 min")
    ok(f"Bridge root: 0x{bridge_root.hex()[:16]}...")

    info("Fetching epoch messages...")
    epoch_msgs = get_epoch_messages(receipt["epoch"], consts)
    info(f"{len(epoch_msgs)} messages in epoch")
    leaf_idx, siblings = find_proof(epoch_msgs, tx_hash, bridge_root)
    ok(f"Proof built — leaf {leaf_idx}, {len(siblings)} siblings")

    info("Sending verifyAndMint()...")
    eth_tx, status = claim_woct(w3, bridge, eth_key, receipt["epoch"], message, siblings, leaf_idx)

    print()
    if status == 1:
        _amt  = to_oct(receipt["amount_raw"])
        _addr = receipt["recipient"]
        print("=" * 55)
        print("  BRIDGE COMPLETE")
        print(f"  {_amt} wOCT minted to {_addr}")
        print(f"  ETH TX: {eth_tx}")
        print("=" * 55)
    else:
        die(f"Transaction reverted — ETH TX: {eth_tx}")

if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        die(str(e))