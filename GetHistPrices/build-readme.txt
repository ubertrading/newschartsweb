== GetHistPrices — Build & Deploy (Linux server) ==

Source:  /opt/GetHistPrices-src/
Deploy:  /opt/GetHistPrices/
Service: supervised by supervisord as "GetHistPrices", runs as user "jonas"
Port:    5000 (localhost only)

-- Build & deploy --

sudo cmake -S /opt/GetHistPrices-src -B /opt/GetHistPrices && sudo make -C /opt/GetHistPrices -j$(nproc)
sudo supervisorctl restart GetHistPrices
sudo supervisorctl status GetHistPrices

-- Check logs --

sudo tail -f /opt/GetHistPrices/stdout
sudo tail -f /opt/GetHistPrices/stderr

-- Test single request --

curl -s -X POST -H "Content-Type: application/json" \
  -d '{"action":"get","symbol":"AUD/USD","timeframe":"t1","timeFrom":"10.28.2026 00:29:00","timeTo":"10.28.2026 00:31:00"}' \
  http://127.0.0.1:5000/hist/

-- Test concurrent requests (simulates two chart iframes) --

curl -s -X POST -H "Content-Type: application/json" \
  -d '{"action":"get","symbol":"AUD/USD","timeframe":"t1","timeFrom":"10.28.2026 00:29:00","timeTo":"10.28.2026 00:31:00"}' \
  http://127.0.0.1:5000/hist/ &

curl -s -X POST -H "Content-Type: application/json" \
  -d '{"action":"get","symbol":"AUD/JPY","timeframe":"t1","timeFrom":"10.28.2026 00:29:00","timeTo":"10.28.2026 00:31:00"}' \
  http://127.0.0.1:5000/hist/ &

wait && echo "=== Both done ==="

-- Notes --

- Windows path (dev copy): d:\Documents\dev\nrreporttest-dukas\GetHistPrices\
- Server source is canonical: always edit /opt/GetHistPrices-src/src/main.cpp on server
- ForexConnect .so libs live in /opt/GetHistPrices/ alongside the binary
- If ldd shows missing .so files, run from /opt/GetHistPrices/ (not from any other dir)
- Web root: /home/jlippuner/quantflash/www/
- graph.php calls download_data.py first, then falls back to GetHistPrices via curl
