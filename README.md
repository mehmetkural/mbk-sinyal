# MBK Sinyal Tarayıcı

UT Bot + Linear Regression Candles + 250.000 $ hacim şartı + 2 saatlik onay.
Binance'in herkese açık verisini 15 dakikada bir tarar, sinyal varsa ntfy ile telefona bildirim gönderir.
**Emir göndermez. Yatırım tavsiyesi değildir.**

## Nasıl çalışır
- `.github/workflows/tarama.yml` her 15 dakikada bir GitHub Actions'ta `mbk_scanner.py`'yi çalıştırır.
- ntfy kanal adı repoda yazmaz; **Settings → Secrets and variables → Actions → `NTFY_TOPIC`** secret'ından okunur.
- Gönderilen son sinyal `state.json` dosyasına yazılır, böylece aynı sinyal iki kez gelmez.

## Elle çalıştırma
Actions → "MBK Sinyal Tarama" → **Run workflow** → `mod`:
- `test`: telefona deneme bildirimi gönderir
- `gecmis`: son ~2 günün sinyallerini (geçen/elenen) log'a yazar, bildirim göndermez

## Ayarlar (`config.json`)
| Alan | Açıklama |
|---|---|
| `semboller` | İzlenen Binance USDT pariteleri |
| `tf` / `htf` | Sinyal zaman dilimi (15m) / onay zaman dilimi (2h) |
| `key`, `atr_per`, `kaynak` | UT Bot ayarları (`kaynak`: linreg / close / heikin) |
| `lr_len`, `sig_len`, `sig_sma`, `lr_filtre` | LinReg Candles ayarları |
| `min_hacim_usd`, `hacim_modu` | Hacim şartı (`mum` veya `24s`) |
| `htf_tip` | 2S onay tipi: `ut`, `linreg`, `ut+linreg` |

## Mac'te çalıştırmak (alternatif)
`bash kur.sh` her 15 dakikada bir çalışan bir launchd görevi kurar, `bash kaldir.sh` kaldırır. Bu durumda `config.json`'daki `ntfy_topic` alanına kanal adını yaz.
