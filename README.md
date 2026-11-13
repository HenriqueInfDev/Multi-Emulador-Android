# Android Emulator Manager

Gerenciador para Windows de até **12 celulares Android virtuais independentes**, usando a infraestrutura oficial
do Android SDK (Android Emulator, ADB, AVD e aceleração WHPX). Não é um emulador próprio: ele cria, liga, desliga
e cuida dos emuladores oficiais do Google.

## Como usar

- **Executável:** `dist\AndroidEmulatorManager\AndroidEmulatorManager.exe`. Gere-o com `build.bat`.
- **Pelo código-fonte:** `python main.py`. Precisa de Python 3.11+ e `pip install -r requirements.txt`.

Na primeira vez, se faltar alguma dependência, o **assistente de dependências** abre sozinho. Ele instala:

| Dependência | De onde vem | Observação |
|---|---|---|
| Java (JDK 21) | Eclipse Adoptium (Temurin) | Vai para `%LOCALAPPDATA%\AndroidEmulatorManager\tools`; não precisa de administrador. |
| Command-line Tools (avdmanager, sdkmanager) | repositório oficial do Google | Checksum verificado. |
| Platform-Tools (ADB), Android Emulator, imagem do Android | `sdkmanager` oficial | Só depois que você aceita as licenças na tela. |
| Aceleração WHPX | recurso do Windows | Pede permissão de administrador e exige reiniciar o PC. |

O Python e o PySide6 já vão embutidos no `.exe`.

## Quantos celulares cabem ao mesmo tempo

Medido com celulares Android 10 com Play Store, com janela:

- **Memória por celular:** cada um usa **cerca de 3 GB de RAM** de verdade. O emulador exige no mínimo 2 GB
  nas imagens com Google Play, e a parte gráfica consome mais ~1 GB.
- **Quantos cabem:**

  | RAM do PC | Celulares ligados ao mesmo tempo (aprox.) |
  |---|---|
  | 16 GB | 2 a 3 |
  | 32 GB | 7 a 8 |
  | 64 GB | 12 |

- **Proteção:** antes de ligar, o gerenciador confere a RAM livre e não liga um celular que não caiba. Se você
  insistir num celular individual, ele pede confirmação.

Os 12 celulares sempre existem, cada um com seus próprios dados. O limite vale só para quantos ficam
**ligados** ao mesmo tempo.

## Funções

- **Grade com os 12 celulares** (`celular_01` … `celular_12`). Cada card mostra:
  - estado: ligado, inicializando ou desligado;
  - versão do Android, RAM, armazenamento, tela e data do último backup.
- **Ações por celular:** iniciar, desligar, reiniciar, mostrar a janela, instalar APK, ajustes, arquivos e backup.
- **Ações em grupo:** marque os cards e use "Iniciar selecionados" ou "Desligar selecionados".
- **Organizar janelas:** distribui em grade, na tela, as janelas de todos os celulares ligados. Com cards
  selecionados, organiza só esses.
- **Instalar APK** em um ou vários celulares ao mesmo tempo, com resultado por celular. Também aceita split APK.
- **Backups:**
  - criar, restaurar, exportar, importar e excluir;
  - vários backups por celular, cada um com data e hora;
  - um backup nunca é sobrescrito.
- **Arquivos:**
  - abrir a pasta de dados do celular;
  - enviar arquivos para a pasta Download do celular;
  - copiar Download e DCIM para o PC.
- **Desempenho:**
  - limite de emuladores ligados ao mesmo tempo;
  - aviso de memória alta e checagem de RAM livre antes de ligar;
  - modo sem janela e inicialização automática opcional.

## Segurança dos dados

- Cada celular é um AVD com pasta própria. Se dois celulares apontarem para a mesma pasta, o gerenciador bloqueia.
- Um AVD existente **nunca é recriado nem formatado**: o `avdmanager` é chamado sem `--force`.
- O `config.ini` só é alterado com o celular desligado. Antes da alteração fica uma cópia `.bak`, e a gravação é atômica.
- **Desligamento seguro:**
  - grava o disco (`sync`) e desliga o Android de verdade (`reboot -p`);
  - "forçar encerramento" só acontece se você confirmar.
- **Quick boot desligado por padrão:** todos os dados ficam no disco do celular. Ele pode ser ativado por
  celular, com aviso.
- **O status "Ligado"** só aparece quando o Android terminou de iniciar **e** o armazenamento do usuário está montado.
- **Backup e restauração:**
  - só com o celular desligado;
  - a cópia é feita numa pasta `.incompleto` e só vira backup válido no final;
  - a restauração guarda o estado atual como backup automático e desfaz tudo se a cópia falhar.
- **Uma instância só:** abrir o gerenciador duas vezes é bloqueado.

## Onde ficam os arquivos

| O quê | Pasta |
|---|---|
| Celulares (AVDs) | `%USERPROFILE%\.android\avd\celular_XX.avd` (configurável) |
| Backups | `%USERPROFILE%\AndroidEmulatorManager\Backups\celular_XX\` (configurável) |
| Configurações do gerenciador | `%APPDATA%\AndroidEmulatorManager\settings.json` |
| Logs (gerenciador e cada emulador) | `%APPDATA%\AndroidEmulatorManager\logs\` |

## Estrutura do código

```
main.py               inicialização, log, instância única
config/settings.py    configurações (JSON) e nomes dos celulares
services/sdk.py       detecção do SDK, imagens do sistema, aceleração
services/adb.py       comandos ADB
services/deps.py      detecção e instalação das dependências
emulators/avd.py      leitura/criação/configuração dos AVDs
emulators/manager.py  estado, iniciar/desligar/reiniciar, janelas
backup/backup.py      backup, restauração, exportação e importação
ui/                   interface PySide6 (janela principal, cards, diálogos, tema)
utils/                execução de processos, sistema, início com o Windows
```
