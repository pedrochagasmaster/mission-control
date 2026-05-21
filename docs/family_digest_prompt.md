# Diário da Família - Formato e Diretrizes

## Objetivo
Produzir um draft diário já pronto para envio no chat da Nina (Rosey), com conteúdo personalizado sobre desenvolvimento infantil, clima e momentos da família.

## Elementos Obrigatórios

### 1. Informações Contextuais
- Data atual e dia da semana
- Clima de Jundiaí/Medeiros (temperatura, condições)
- Idade atual da Isabel (nascida em 2026-02-11)

### 2. Tema do Dia
- Escolher tema adequado à idade atual da Isabel
- Consultar base de conhecimento parenting ou web_search quando necessário
- Evitar repetição de temas recentes (verificar family_digest_topics.md)
- Focar em desenvolvimento infantil, marcos, brincadeiras, dicas práticas

### 3. Estrutura da Mensagem

A mensagem deve começar com a linha de clima/cidade no topo:
```
🌤️ Jundiaí, DD de mês de AAAA — Descrição do dia e temperatura.
```

Conteúdo principal:
- Saudação natural e acolhedora ("Oi, gente!", "Bom dia, família!")
- Contexto sobre a idade atual da Isabel
- Tema do dia desenvolvido de forma pessoal e calorosa
- Dicas práticas que os pais possam aplicar
- Fechamento carinhoso

### 4. Tom e Estilo
- Linguagem natural, como uma conversa entre amigas
- Tom acolhedor, sem julgamentos
- Evitar linguagem técnica excessiva
- Usar emojis pontualmente para dar vida ao texto
- Escrever em primeira pessoa como a Nina (Rosey)

## O que NUNCA incluir
- Títulos markdown (# Diário da Família)
- Seções de preview, resumo ou "estado geral"
- Texto do tipo "se aprovar", "preview", "rascunho"
- Menções a arquivos, docs, fontes ou processos internos
- Links ou citações de fontes no corpo do texto
- Seção de referências bibliográficas
- Linguagem robótica ou excessivamente formal

## Formato de Saída

Salvar em `/home/pedro/.openclaw/workspace/memory/daily_digest_draft.json`:

```json
{
  "date": "YYYY-MM-DD",
  "tema": "Tema escolhido",
  "message": "MENSAGEM FINAL pronta para envio"
}
```

## Resposta Final
Ao final da geração, responder exatamente:
```
Draft gerado: [tema]
```

## Comprimento
- Entre 300 e 600 palavras
- Mensagem completa e pronta para envio
- Não deixar pendências ou placeholders
