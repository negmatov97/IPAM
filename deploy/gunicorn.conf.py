# Gunicorn sozlamalari: gunicorn -c deploy/gunicorn.conf.py config.wsgi
import multiprocessing

bind = "127.0.0.1:8000"          # faqat Nginx orqali kiriladi
workers = min(multiprocessing.cpu_count() * 2 + 1, 8)
timeout = 60                      # katta PDF/Word hisobotlar uchun
graceful_timeout = 30
max_requests = 1000               # xotira sizib chiqmasligi uchun ishchilarni vaqti-vaqti bilan yangilash
max_requests_jitter = 100
accesslog = "-"
errorlog = "-"
forwarded_allow_ips = "127.0.0.1"
