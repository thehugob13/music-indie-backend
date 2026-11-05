# Deploy na Render

Este pacote é o backend Music Indie, pronto para um Web Service Docker na Render. O Blueprint `render.yaml` usa o plano gratuito de testes. Nenhum recurso Render foi criado e nenhuma cobrança foi ativada.

## Ativar

1. Crie sua conta em https://dashboard.render.com/register e conecte o GitHub pelo painel.
2. Depois de autorizar o envio do código ao repositório privado `thehugob13/music-indie-backend`, use **New → Blueprint** e selecione esse repositório.
3. Revise os recursos propostos. Insira sua chave em `YOUTUBE_API_KEY` quando o painel solicitar; habilite YouTube Data API v3 no Google Cloud.
4. Aguarde o serviço ficar **Live**. Acesse a URL HTTPS exibida pela Render, acrescente `/health` e confira `status: ok` e `search_configured: true`.
5. No Music Indie Android, abra **Conectar servidor de músicas** e cole a URL HTTPS base, sem `/health`.

Não envie a chave pelo chat, código ou aplicativo. A chave deve ficar nas variáveis privadas da Render. Esse deploy usa Python 3.12, Node 22, FFmpeg e yt-dlp.

## Limitações do plano gratuito

O disco é efêmero e o serviço pode suspender quando ocioso. Sessões, trabalhos e MP3s temporários podem desaparecer após reinício/redeploy. Downloads já concluídos no celular continuam no cache privado do app. O primeiro acesso após suspensão pode demorar. A extração YouTube ainda exige teste real: os provedores podem receber restrições da fonte.

Para preservar a fila entre reinícios, escolha no painel um plano que permita disco persistente, monte-o em `/data` e mude `MEDIA_DATA_DIR` para `/data/media`. Revise o preço mostrado pela Render antes de confirmar; o Blueprint gratuito não ativa esse recurso pago.

## Verificações realizadas

O backend principal passou em nove testes, incluindo conversão real de MP4 sintético para MP3 e download autenticado com HTTP Range. O entrypoint foi validado por `sh -n` e o código por `py_compile`. A construção Docker local foi tentada, mas não concluída por falta de espaço no ambiente; ainda exige build na Render. Nenhum endpoint público foi validado.
