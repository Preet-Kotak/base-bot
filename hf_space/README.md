---
title: YOLO Extract API
emoji: 🏗️
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: 5.9.1
app_file: app.py
pinned: false
---

# YOLO Extract API

Internal YOLO inference server for the Clash of Clans Capital Base Discord bot.

Exposes `POST /extract` — accepts a base screenshot, returns building layout JSON.

Protected by `X-API-Key` header. Not for public use.
