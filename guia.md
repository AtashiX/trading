# Guía de puesta en marcha — Scalping Bot

## Archivos del proyecto

```
trading_bot/
├── config.py          ← ÚNICO archivo que debes editar
├── risk_manager.py    ← No tocar
├── bot.py             ← No tocar
├── requirements.txt   ← Dependencias
```

---

## PASO 1 — Crear cuenta en Alpaca y obtener las API keys

1. Ve a https://alpaca.markets y haz clic en **"Get Started"**
2. Rellena el formulario de registro (email + contraseña). No necesitas tarjeta.
3. Una vez dentro, en la parte superior verás un selector **"Live Trading" / "Paper Trading"**.
   Cambia a **Paper Trading**.
4. Ve al menú de la izquierda → **"API Keys"** → **"Generate New Key"**
5. Copia y guarda en un lugar seguro:
   - `API Key ID`  (empieza por PK...)
   - `Secret Key`  (solo se muestra una vez)

> Paper Trading es dinero ficticio con precios reales. No te cobran nada
> y no necesitas depositar dinero real todavía.

---

## PASO 2 — Subir el código a GitHub

Necesitas una cuenta en https://github.com (gratis).

1. Haz clic en **"New repository"** → ponle nombre (ej. `scalping-bot`) → **Private** → Create
2. En tu ordenador, crea una carpeta `trading_bot` y mete los 4 archivos dentro
3. Abre una terminal en esa carpeta y ejecuta:

```bash
git init
git add .
git commit -m "primer commit"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/scalping-bot.git
git push -u origin main
```

> IMPORTANTE: No escribas las API keys en config.py antes de subir a GitHub.
> Las pondrás en Render como variables de entorno (paso 4).

---

## PASO 3 — Desplegar en Render

1. Ve a https://render.com y crea una cuenta (gratis, no necesitas tarjeta)
2. Haz clic en **"New +"** → **"Web Service"**
3. Conecta tu cuenta de GitHub y selecciona el repositorio `scalping-bot`
4. Rellena así:
   - **Name:** scalping-bot (o el que quieras)
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
   - **Instance Type:** Free
5. Antes de hacer deploy, ve a la sección **"Environment Variables"** y añade:

   | Key                | Value                        |
   |--------------------|------------------------------|
   | ALPACA_API_KEY     | (tu API Key de Alpaca)       |
   | ALPACA_SECRET_KEY  | (tu Secret Key de Alpaca)    |
   | MODE               | paper                        |

6. Haz clic en **"Create Web Service"**

Render tardará 2-3 minutos en desplegar. Cuando termine verás una URL tipo:
`https://scalping-bot-xxxx.onrender.com`

Entra en esa URL y verás el dashboard del bot.

---

## PASO 4 — Configurar cron-job.org para mantener Render despierto

Render duerme el servicio si no recibe tráfico en 15 minutos.
cron-job.org lo pings cada 10 minutos para evitarlo, completamente gratis.

1. Ve a https://cron-job.org y crea una cuenta
2. Haz clic en **"Create cronjob"**
3. Rellena:
   - **Title:** keep-bot-alive
   - **URL:** `https://scalping-bot-xxxx.onrender.com/health`
     (cambia xxxx por tu URL real de Render)
   - **Schedule:** Every 10 minutes
     (en el selector elige "Every" → "10 minutes")
4. Haz clic en **"Create"**

A partir de ahora el bot corre 24/7 sin depender de tu ordenador ni conexión.

---

## PASO 5 — Verificar que todo funciona

1. Entra en tu URL de Render (ej. `https://scalping-bot-xxxx.onrender.com`)
2. Deberías ver el dashboard con:
   - Modo: PAPER
   - PnL hoy: +0.00
   - Sin posiciones abiertas
3. Espera a que el mercado esté abierto (lunes-viernes 15:30-22:00 hora España)
   y observa cómo el bot empieza a operar

---

## PASO 6 — Monitorización durante las primeras semanas

Cada día (o cada pocos días) entra en el dashboard y observa:

- ¿El bot está encontrando señales? (debe haber trades en la tabla)
- ¿El PnL diario es positivo más días de los que es negativo?
- ¿Algún símbolo genera muchos stop-loss? (indicio de que ese símbolo da señales falsas)

Revisa también el log en Render:
Render → tu servicio → pestaña **"Logs"**
Verás cada operación en tiempo real.

---

## PASO 7 — Pasar a Live (solo cuando estés listo)

Después de 4-6 semanas de paper trading con resultados consistentes:

1. En Alpaca, crea tu cuenta Live y deposita los 100 USD (o los que quieras)
2. Genera nuevas API Keys en la sección **Live Trading** de Alpaca
3. En Render → tu servicio → **Environment Variables**:
   - Actualiza `ALPACA_API_KEY` con la key de Live
   - Actualiza `ALPACA_SECRET_KEY` con el secret de Live
   - Cambia `MODE` de `paper` a `live`
4. Render se reinicia automáticamente con la nueva config

---

## Ajustes recomendados durante el paper trading

Si el bot opera muy poco (pocas señales):
- En config.py, reduce `EMA_LENTA` de 13 a 8
- Sube `RSI_SOBRECOMPRA` de 60 a 65

Si el bot tiene muchos stop-loss seguidos:
- Sube `STOP_LOSS_PCT` de 0.006 a 0.008
- Baja `MAX_POSICIONES` de 2 a 1

Si quieres más operaciones al día:
- Añade más símbolos del Tier 2 en config.py
- Reduce `SLEEP_SEGUNDOS` de 30 a 20

---

## Horario del mercado (hora España)

| Temporada    | Apertura | Cierre |
|--------------|----------|--------|
| Verano (DST) | 15:30    | 22:00  |
| Invierno     | 16:30    | 23:00  |

El bot no ejecutará operaciones reales fuera de ese horario.
Alpaca rechazará las órdenes (en paper trading las gestiona igualmente).

---

## Retiro mensual

Cuando el dashboard muestre "Retiro disponible > 0":
1. Entra en tu cuenta Live de Alpaca
2. Ve a **"Transfers"** → **"Withdraw"**
3. Transfiere a tu cuenta bancaria

El tiempo de transferencia suele ser 1-3 días hábiles.