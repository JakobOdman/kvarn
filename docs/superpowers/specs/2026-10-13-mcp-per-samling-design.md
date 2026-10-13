# MCP-server per samling

Datum: 2026-10-13. Gäller Kvarn och Kvarn Enterprise.

## Syfte

Kunder ska kunna koppla en samling i Kvarn till Claude (claude.ai, Claude Desktop) eller Microsoft Copilot Studio och
ställa frågor om samlingens tabeller, med källa (dokument, sida, citat) i svaren. MCP-servern är en del av produkten,
inte ett demoverktyg.

Ingen kod per mall: servern är generisk och formas av samlingens mall (tabeller, fält, beskrivningar, val). En ny mall
ger en färdig MCP utan att något byggs.

## Beslut

- **Enhet: samlingen.** En samling = en upphandling (eller motsvarande). Ingen gruppering inom en samling i v1; flera
  upphandlingar = flera samlingar, en MCP var.
- **Data: samlingens live-extraktion**, samma som fliken Integrera. Kräver att Extrahera automatiskt är påslaget.
- **Åtkomst: samlingens befintliga API-nyckel** som `Authorization: Bearer kvarn_...`. Fungerar i Claudes anpassade
  connectors (Request headers) och i Copilot Studio (API-nyckel, header `Authorization`, värde `Bearer ...`).
  OAuth (Supabase i Kvarn, Entra i Enterprise) är ett senare steg, när en kund kräver personlig inloggning.
- **Brytare per samling**, avstängd som standard.
- **Bara läsning.**

## Arkitektur

**`api/mcp.py`**, samma fil i båda repona. Beror bara på `live_tables()`-kontrollen, mallen (`Template`) och
`db.py`. Inget från Vercel, Supabase eller Azure. Byggs först i Kvarn och kopieras sedan oförändrad till
kvarn-enterprise, med en egen commit där (repona har skilda historiker).

**Adress:** `POST {bas}/api/public/folders/{folder_id}/mcp`, på den publika routern bredvid tabelladresserna.
I Enterprise släpper Easy Auth redan igenom anonyma anrop till `/api/public`, så inget ändras i infrastrukturen.

**Protokoll:** MCP över Streamable HTTP, tillståndslöst: en `POST` med JSON-RPC in och JSON ut, inga sessioner,
ingen SSE. Egenskrivet (cirka 60 rader) i stället för MCP-SDK:n, vars session manager kräver en livscykel som inte
passar Vercels funktioner. Metoder:

- `initialize`: protokollversion, `serverInfo.name` = samlingens namn, `capabilities.tools`, och `instructions`.
- `notifications/initialized` och andra notifieringar: 202 utan innehåll.
- `tools/list`: de två verktygen.
- `tools/call`: kör verktyget.
- Okänd metod: JSON-RPC-fel `-32601`.
- `GET` på adressen: 405 (ingen SSE-ström).

**Data per anrop:** live-extraktionen läses in i en SQLite i minnet, en tabell per tabell i mallen, med
`PRAGMA query_only = ON`. Claudes SQL når aldrig Postgres eller andra samlingar.

Kolumner i varje tabell: `samling` (samlingens namn), `dokument` (filnamnet), mallens fält i mallens ordning,
`sida`, `citat`. `samling` finns med redan i v1, där den alltid har samma värde, så att strukturen är densamma när en
MCP över flera samlingar kommer (se Utanför v1). Tomma strängar
blir `NULL`, tal lagras som tal.

## Verktyg

**`kvarn_schema`** (inga argument). Anropas först. Returnerar:

- samlingens namn, mallens namn, dokumenten i samlingen
- per tabell: kolumner med mallens fältbeskrivning, antal rader
- per fält med `choices` i mallen: de värden som förekommer i datan

**`kvarn_sql`** (`fraga: str`). En `SELECT` mot tabellerna, högst 200 rader, som en lista med objekt. Fel i SQL
eller försök att skriva ger ett läsbart verktygsfel som hänvisar till `kvarn_schema`.

**Instruktion** (i `initialize`): "Svara bara utifrån tabellerna. Ange alltid källa: dokument, sida och citat.
Anropa kvarn_schema först."

## Brytare och fliken Integrera

- Ny kolumn: `folders.mcp_enabled BOOLEAN NOT NULL DEFAULT false`. I Kvarn läggs den i `schema.sql` och körs mot
  Supabase före push. I Enterprise skapar appen tabellerna vid start.
- Ny endpoint för att slå av och på, bakom inloggningen (samma mönster som `auto_extract`).
- Fliken Integrera får en rad "MCP-server" med brytaren. Påslagen visas adressen och en kort instruktion för Claude
  och Copilot Studio. Nyckeln skapas med den befintliga knappen; saknas nyckel visas det.
- Tabelladresserna påverkas inte av brytaren.

## Fel

| Läge | Svar |
|---|---|
| Fel eller saknad nyckel | 401 (som i dag) |
| MCP avstängt för samlingen | 404 "MCP är inte påslaget för samlingen." |
| Ingen live-extraktion | Verktygsfel: "Samlingen har ingen aktuell tabell. Slå på Extrahera automatiskt i Kvarn." |
| Fel i SQL, eller inte `SELECT` | Verktygsfel med SQLites meddelande och hänvisning till `kvarn_schema` |
| Felaktig JSON-RPC | JSON-RPC-fel `-32600`/`-32601`/`-32602` |

Verktygsfel returneras som `isError: true` i `tools/call`, så att Claude kan förklara dem för användaren.

## Tester

pytest, utan AI-anrop, mot testernas egen Postgres. Filen `tests/test_mcp.py` kopieras till kvarn-enterprise.

- `initialize`, `tools/list`, `tools/call` för båda verktygen mot en samling med live-extraktion
- 401 vid fel nyckel, 404 när MCP är avstängt, verktygsfel när live-extraktion saknas
- `kvarn_sql` vägrar skriva och kapar vid 200 rader
- `kvarn_schema` visar fältbeskrivningar och förekommande värden för `choices`
- brytaren: av som standard, går att slå på och av, bara för ägaren

Manuellt: lokalt med `claude mcp add --transport http <namn> <adress> --header "Authorization: Bearer ..."`, sedan
som anpassad connector i claude.ai mot driften, och i Copilot Studio.

## Enterprise

Löftet i Enterprise är att datan aldrig passerar oss. En Claude-connector gör att anrop går från Anthropic in till
kundens Azure och att svaren hamnar hos Anthropic; med Copilot Studio stannar allt hos Microsoft. Lathunden för
Enterprise beskriver Copilot Studio först och Claude som ett medvetet val av kunden.

## Utanför v1

- MCP per mall över flera samlingar. Samling och mall är två entiteter (en samling kan köras med flera mallar, en
  mall används i många samlingar). En sådan MCP hör därför hemma på mallen, med egen nyckel och adress, och ser alla
  samlingar som har mallen som sin mall. Tas när v1 har använts en tid.
- Gruppering av dokument i en samling (flera upphandlingar)
- OAuth (Supabase / Entra)
- Skrivande verktyg, uppladdning, originalfiler
- Mallspecifika verktyg
- Anropsgräns (gäller hela `/api/public`, tas separat)
