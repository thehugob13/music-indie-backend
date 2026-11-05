# Music Indie 0.4 — métodos gratuitos

Esta versão remove a integração paga do Yout e adiciona Fontes livres via Internet Archive. O modo YouTube permanece usando yt-dlp/FFmpeg, sem API paga de conversão. A busca YouTube usa a chave Google já configurada; a busca Archive não precisa de chave de API.

## Atualização do servidor existente

1. Extraia `music-indie-backend-gratuito.zip`.
2. No repositório público https://github.com/thehugob13/music-indie-backend envie para a raiz os arquivos **app.py**, **archive_source.py** e **Dockerfile**, substituindo os existentes quando necessário. O novo módulo precisa ser incluído pelo Dockerfile, ou o serviço não inicia.
3. Confirme o commit e aguarde a Render ficar Live. A chave YOUTUBE_API_KEY existente pode permanecer. Remova YOUT_API_KEY se tiver sido adicionada; nenhuma chamada ao Yout é feita nesta versão.
4. Em /health confira `free_catalog_enabled: true` e `media_provider: free`.
5. Instale o APK 0.4 sobre a versão anterior. Na Busca, selecione Fontes livres ou YouTube.

O APK informa que o backend precisa ser atualizado quando o serviço antigo não anuncia suporte ao catálogo livre. A configuração da URL continua https://music-indie-backend.onrender.com . Não precisa enviar ou inserir chaves no APK.

## O que funciona e o que falta validar

- Fontes livres: pesquisa metadados de áudio do Internet Archive, aceita CC BY/CC BY-SA/CC0/declaração de domínio público, lista arquivos individuais e reconfirma licença antes de baixar.
- A obtenção do áudio é feita no servidor a partir do Archive, com limite de tamanho e redirecionamentos HTTPS restritos a archive.org. FFmpeg converte para MP3 e o app usa o mesmo fluxo privado de download/cache.
- Em teste real do ambiente de desenvolvimento, a busca Beethoven retornou cinco resultados. Uma gravação declarada de domínio público foi baixada e convertida para MP3; ffprobe validou 142,89 segundos. Evidência em free-source-live-check.json.
- 16 testes do backend e 3 testes unitários Android passaram; APK compilado. O fluxo novo ainda não foi testado em aparelho nem na Render, pois falta atualizar os arquivos do serviço.
- YouTube: o backend público ainda está na versão inicial e falhou ao obter o áudio. A nova versão inclui diagnóstico de falhas. Não há garantia de que trocar ferramenta ou usar uma biblioteca gratuita contorne restrições da fonte. Não foram adicionados cookies, login, rotação de IP ou mecanismos de contorno.

O catálogo livre não equivale ao catálogo comercial do YouTube/Spotify; pode conter versões diferentes, apresentações históricas e gravações independentes. O app preserva fonte e licença para conferência.

Software de conversão gratuito não torna a hospedagem ilimitada. O plano gratuito da Render pode suspender e perder os trabalhos temporários após reinícios; downloads já concluídos no celular continuam no cache.
