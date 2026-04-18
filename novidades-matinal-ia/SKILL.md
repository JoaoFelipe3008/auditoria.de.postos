---
name: novidades-matinal-ia
description: >
  Busca as principais notícias de IA das últimas 24h e gera um dashboard HTML em português para abrir no browser.
  Use esta skill SEMPRE que o usuário pedir "briefing de hoje", "novidades de IA", "o que aconteceu em IA", "resumo de IA",
  "últimas notícias de inteligência artificial", "me atualiza sobre IA", "novidades do dia", "morning briefing",
  "o que rolou em IA", "atualizações de IA", "news de IA", ou qualquer variação similar pedindo um resumo/briefing
  de notícias recentes sobre inteligência artificial. A skill acessa Hacker News e TechCrunch, filtra conteúdo
  relevante sobre IA, traduz tudo para português brasileiro, e produz um dashboard HTML autocontido com design dark
  mode elegante salvo como novidades-YYYY-MM-DD.html, que é aberto automaticamente no browser ao final.
---

# Novidades Matinal de IA

Você é um curador de notícias de IA. Sua missão: buscar as principais notícias de inteligência artificial das últimas 24h, traduzir e resumir em português brasileiro, e gerar um dashboard HTML elegante.

## Passo 1 — Buscar as fontes

Use `WebFetch` para acessar **ambas** as URLs abaixo. Se uma falhar, continue com a outra e registre o erro.

**Fonte 1 — Hacker News:**
- URL: https://news.ycombinator.com/newest
- Extraia todos os títulos de posts visíveis na página junto com seus links.

**Fonte 2 — TechCrunch AI:**
- URL: https://techcrunch.com/category/artificial-intelligence/
- Extraia os títulos dos artigos, seus links e subtítulos quando disponíveis.

## Passo 2 — Filtrar notícias relevantes de IA

Selecione apenas os itens relacionados a:

**Prioridade ALTA — Destaques (3-5 itens):**
- Agentes de IA, multi-agentes, agentic AI
- Anthropic, Claude (qualquer versão/produto)
- OpenAI, ChatGPT, GPT-4, GPT-5, o1, o3
- Google Gemini, Gemma, DeepMind
- Meta AI, Llama (qualquer versão)
- Lançamentos de novos modelos ou produtos de IA
- Novas funcionalidades significativas de plataformas de IA

**Prioridade NORMAL — Mais Notícias:**
- LLMs, large language models, foundation models
- RAG, embeddings, vector databases
- AI coding, Copilot, Cursor, ferramentas dev com IA
- Computer vision, multimodal AI
- AI regulation, safety, alignment
- Startups de IA com financiamento ou lançamento relevante
- Benchmarks, pesquisas acadêmicas sobre LLMs
- Tendências de IA relevantes para builders/desenvolvedores

**Ignorar:** hardware puro sem IA, política/geopolítica sem IA, entretenimento sem IA, artigos de opinião vagos.

## Passo 3 — Resumir e traduzir

Para cada notícia selecionada:
1. Classifique como "destaque" (3-5) ou "mais notícias"
2. Traduza o título para português brasileiro — tradução natural, não literal
3. Resumo em português: destaques = 2-3 linhas; demais = 1-2 linhas
4. Identifique a fonte: "Hacker News" ou "TechCrunch"
5. Preserve o link original

## Passo 4 — Frase-resumo do dia

Escreva uma frase curta e inteligente (máx 120 caracteres) capturando o espírito do dia em IA.
Exemplo: "Anthropic e OpenAI dominam as manchetes com novos modelos e controvérsias."

## Passo 5 — Gerar o HTML

Gere um arquivo HTML **completo e autocontido** (zero dependências externas — sem CDN, sem Google Fonts, sem scripts externos).

Formate a data atual em português: ex. "SÁBADO, 12 DE ABRIL DE 2025"

Template de design a usar:

```html
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Novidades de IA — [DATA]</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  :root{
    --bg:#0a0a0a;--card:#111111;--border:#1e1e1e;
    --text:#e5e5e5;--muted:#888888;
    --green:#00ff87;--blue:#3b82f6;
    --font:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
    --mono:'Courier New','Lucida Console',monospace
  }
  body{background:var(--bg);color:var(--text);font-family:var(--font);line-height:1.6;min-height:100vh;padding:0 1rem 3rem}
  .container{max-width:860px;margin:0 auto}
  header{padding:3rem 0 2rem;border-bottom:1px solid var(--border);margin-bottom:2.5rem}
  header h1{font-size:1.75rem;font-weight:700;letter-spacing:-.02em;color:#fff}
  header h1 span{color:var(--green)}
  .date{font-family:var(--mono);font-size:.8rem;color:var(--muted);margin-top:.35rem;text-transform:uppercase;letter-spacing:.05em}
  .summary{margin-top:.75rem;color:var(--muted);font-size:.95rem;font-style:italic}
  .section-title{font-size:.75rem;font-weight:600;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin-bottom:1rem;display:flex;align-items:center;gap:.5rem}
  .section-title::after{content:'';flex:1;height:1px;background:var(--border)}
  .destaques{margin-bottom:2.5rem}
  .d-card{background:var(--card);border:1px solid var(--border);border-left:3px solid var(--green);border-radius:6px;padding:1.25rem 1.5rem;margin-bottom:.75rem;text-decoration:none;display:block;transition:background .15s}
  .d-card:hover{background:#161616}
  .d-card .src{font-family:var(--mono);font-size:.7rem;color:var(--green);text-transform:uppercase;letter-spacing:.08em;margin-bottom:.5rem}
  .d-card .ttl{font-size:1.05rem;font-weight:600;color:#fff;margin-bottom:.5rem;line-height:1.4}
  .d-card .dsc{font-size:.875rem;color:#aaa;line-height:1.55}
  .mais{margin-bottom:2.5rem}
  .n-card{background:var(--card);border:1px solid var(--border);border-left:3px solid var(--blue);border-radius:6px;padding:.85rem 1.25rem;margin-bottom:.5rem;text-decoration:none;display:block;transition:background .15s}
  .n-card:hover{background:#161616}
  .n-card .src{font-family:var(--mono);font-size:.65rem;color:var(--blue);text-transform:uppercase;letter-spacing:.08em;margin-bottom:.3rem}
  .n-card .ttl{font-size:.9rem;font-weight:600;color:#ddd;margin-bottom:.3rem;line-height:1.4}
  .n-card .dsc{font-size:.8rem;color:#888;line-height:1.5}
  footer{border-top:1px solid var(--border);padding-top:1.25rem;display:flex;justify-content:space-between;flex-wrap:wrap;gap:.5rem}
  footer .ts{font-family:var(--mono);font-size:.7rem;color:var(--muted)}
  footer .srcs{font-size:.75rem;color:var(--muted)}
  footer .srcs span{color:#555;margin:0 .25rem}
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="date">[DATA EM MAIÚSCULAS]</div>
    <h1>&#9728;&#65039; Novidades de <span>IA</span></h1>
    <div class="summary">[FRASE-RESUMO DO DIA]</div>
  </header>

  <section class="destaques">
    <div class="section-title">&#128293; Destaques</div>
    [INSERIR 3-5 DESTAQUE CARDS]
  </section>

  <section class="mais">
    <div class="section-title">&#128240; Mais Notícias</div>
    [INSERIR DEMAIS NOTÍCIAS]
  </section>

  <footer>
    <div class="ts">Gerado em [TIMESTAMP ISO] · Claude</div>
    <div class="srcs">Fontes consultadas<span>·</span>Hacker News<span>·</span>TechCrunch AI</div>
  </footer>
</div>
</body>
</html>
```

Card de destaque:
```html
<a class="d-card" href="[URL_ORIGINAL]" target="_blank" rel="noopener">
  <div class="src">[FONTE]</div>
  <div class="ttl">[TÍTULO TRADUZIDO]</div>
  <div class="dsc">[RESUMO 2-3 LINHAS]</div>
</a>
```

Card de notícia:
```html
<a class="n-card" href="[URL_ORIGINAL]" target="_blank" rel="noopener">
  <div class="src">[FONTE]</div>
  <div class="ttl">[TÍTULO TRADUZIDO]</div>
  <div class="dsc">[RESUMO 1-2 LINHAS]</div>
</a>
```

**Regras:**
- Preencha TODOS os placeholders com conteúdo real
- CSS inline no `<head>` — zero dependências externas
- O arquivo deve abrir corretamente offline

## Passo 6 — Salvar o arquivo

Salve como `novidades-YYYY-MM-DD.html` no diretório de trabalho atual (onde o usuário está rodando o Claude Code).

## Passo 7 — Resumo no terminal

Exiba após salvar:
```
Hacker News:    [N] notícias coletadas
TechCrunch:     [N] notícias coletadas
Total filtrado: [N] notícias de IA
Destaques: [N]  |  Mais notícias: [N]
Arquivo salvo: [CAMINHO COMPLETO]
```
Se uma fonte falhou: `Hacker News: ERRO — não foi possível acessar`

## Passo 8 — Abrir no browser

- **Windows:** execute `start novidades-YYYY-MM-DD.html`
- **macOS:** execute `open novidades-YYYY-MM-DD.html`
- **Linux:** execute `xdg-open novidades-YYYY-MM-DD.html`

Em caso de erro ao abrir, informe o caminho para o usuário abrir manualmente.

---

## Comportamento em caso de falha

- **Uma fonte inacessível:** Continue com a outra; note a falha no terminal e no rodapé do HTML.
- **Ambas inacessíveis:** Gere um HTML com mensagem de erro elegante.
- **Nenhuma notícia de IA em uma fonte:** Use apenas a outra.
- **Erro ao abrir browser:** Informe o caminho do arquivo.
