# Nekonečná detektivka

Tato aplikace je chatová hra s AI postavami v detektivním příběhu, využívající PostgreSQL pro ukládání dat a Redis pro cache.

## Spuštění

1. Vytvoř `.env` soubor podle `.env.example` s tvými hodnotami (OpenAI klíč, DB údaje).
2. Spusť `docker-compose up` – aplikace poběží na portu 8000 (nebo podle PORT v .env).

## Perzistence dat

- **Na školním serveru**: Data PostgreSQL se ukládají do systémového adresáře `/data/pgdata` (nastaveno přes `PGDATA=/data/pgdata` v compose.yml). Tato složka je perzistentní, takže data zůstanou i po restartu kontejnerů.
- **Lokálně**: Bez explicitních volumes se data ukládají pouze v kontejneru. Po `docker-compose down` se ztratí. Pokud potřebuješ lokální perzistenci, přidej zpět `volumes` do compose.yml (ale na škole to není povoleno).

## API Endpoints

- `POST /chat`: Chat s postavou (parametry: character_id, message, session_id)
- `POST /accuse`: Obvinění postavy (parametry: character_id, accusation, session_id)

## Poznámky

- Retry loop v main.py zajišťuje spolehlivé připojení k DB při startu.
- Citlivá data jsou v DB nebo env proměnných, ne v kódu.