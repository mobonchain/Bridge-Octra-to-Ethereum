 <h1 align="center">Hi 👋, I'm Mob</h1>
<h3 align="center">Join the Cryptocurrency Market, make money from Airdrop - Retroactive with me</h3>

- <p align="left"> <img src="https://komarev.com/ghpvc/?username=mobonchain&label=Profile%20views&color=0e75b6&style=flat" alt="mobonchain" /> <a href="https://github.com/mobonchain"> <img src="https://img.shields.io/github/followers/mobonchain?label=Follow&style=social" alt="Follow" /> </a> </p>

- [![TopAME | Bullish - Cheerful](https://img.shields.io/badge/TopAME%20|%20Bullish-Cheerful-blue?logo=telegram&style=flat)](https://t.me/xTopAME)

# Octra Bridge — OCT → wOCT
- **Chức năng:** Tự động **Bridge** native **OCT** từ mạng Octra sang **wOCT** trên **Ethereum**

---

## Yêu cầu
- Ví Octra có OCT
- Ví Ethereum có ETH (để trả gas, tối thiểu ~0.0005 ETH)
- Python 3.10+

---

## Cấu Trúc Thông Tin Cần Có

| Thông tin | Mô tả |
|---|---|
| **Octra Private Key** | Private key dạng base64 của ví đang giữ OCT |
| **Ethereum Private Key** | Private key dạng `0x...` của ví trả gas (không cần là ví nhận wOCT) |
| **Ethereum Recipient** | Địa chỉ ví EVM sẽ nhận wOCT |

> 💡 Ví trả gas và ví nhận wOCT **không cần là một ví** — ví nhận được ghi cố định từ bước Lock, ai cũng có thể trả gas.

---

## Cài Đặt Trên Windows

### Bước 1: Tải và Giải Nén File

1. Nhấn vào nút **<> Code** màu xanh lá cây, sau đó chọn **Download ZIP**.
2. Giải nén file ZIP vào thư mục bạn muốn lưu trữ.

### Bước 2: Cài Đặt Module

1. Mở **Command Prompt (CMD)** trong thư mục chứa mã nguồn.
2. Cài đặt các thư viện yêu cầu bằng lệnh:
   ```bash
   pip install web3 requests eth-abi pynacl
   ```

### Bước 3: Chạy Tool

1. Chạy chương trình bằng lệnh:
   ```bash
   python bridge_octra.py
   ```

2. Nhập lần lượt theo yêu cầu:
   ```
   Ethereum private key (0x):   ← private key ví trả gas ETH
   Octra private key (base64):  ← private key ví Octra chứa OCT
   Ethereum recipient address:  ← địa chỉ EVM nhận wOCT
   ```

3. Nhập số lượng OCT muốn bridge → xác nhận `y` → tool tự động xử lý hoàn toàn

---

## Nếu Bị Timeout (TX Đã Gửi Nhưng Chưa Confirm)

Chạy lại lệnh dưới, **không cần lock lại OCT**:
```bash
python bridge_octra.py --resume <octra_lock_tx_hash>
```

---

## Lưu Ý
- Đảm bảo ví ETH có **ít nhất 0.0005 ETH** trước khi chạy
- Tool sẽ **simulate** trước khi gửi — nếu simulate thất bại sẽ dừng lại, **không mất gas**
- Sau khi bridge thành công, wOCT sẽ xuất hiện trong ví nhận trên Ethereum

---

## Nếu gặp phải bất kỳ vấn đề nào có thể hỏi thêm tại **[TopAME | Chat - Supports](https://t.me/yTopAME)**
