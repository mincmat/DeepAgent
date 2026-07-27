# DeepAgent 🧠

**DeepAgent** convierte a DeepSeek (chat.deepseek.com) en un agente autónomo con acceso completo a tu terminal. A través de una extensión de Chrome y un puente Python local, la IA puede ejecutar comandos, leer/escribir archivos, instalar paquetes y más, directamente en tu computadora.

## Arquitectura

```
DeepSeek Chat ←→ Extensión Chrome ←→ Servidor Python ←→ Shell (bash/zsh/cmd)
```

## Plataformas soportadas

| Plataforma | Shell | Iniciador |
|---|---|---|
| Linux | bash | `DeepAgent_Linux/start.sh` |
| macOS | zsh (predeterminado) | `DeepAgent_macOS/start.command` |
| Windows | cmd.exe | `DeepAgent_Windows/start.bat` |

## Requisitos

- **Python 3** (solo librería estándar — sin dependencias externas)
- **Google Chrome** (para la extensión)
- Una cuenta en [chat.deepseek.com](https://chat.deepseek.com)

## Instalación

1. Clona o descarga este repositorio.
2. Abre Chrome → `chrome://extensions` → Activa **Modo desarrollador** → **Cargar extensión sin empaquetar**.
3. Selecciona la carpeta `DeepAgent_Extension` dentro de la carpeta de tu SO.
4. Ejecuta el iniciador correspondiente a tu sistema:
   - **Linux:** `bash start.sh`
   - **macOS:** Haz doble clic en `start.command`
   - **Windows:** Haz doble clic en `start.bat`
5. Ve a [chat.deepseek.com](https://chat.deepseek.com) y presiona **Iniciar** en el panel flotante.

## Funcionamiento

1. La extensión inyecta un **system prompt** en el chat explicando a DeepSeek cómo usar comandos.
2. Cuando la IA responde con un bloque JSON como `{"action": "execute", "command": "ls -la"}`, la extensión lo detecta automáticamente.
3. El comando se envía al servidor Python local (`localhost:8765`), que lo ejecuta en una shell persistente.
4. La salida se captura y se pega de vuelta en el chat para que la IA la procese.
5. El ciclo se repite: la IA ve la salida y decide el siguiente comando.

## Seguridad

- El servidor solo acepta peticiones desde `chat.deepseek.com` y `chrome-extension://`.
- Los comandos con `sudo` se ejecutan en un entorno aislado que detecta prompts de autenticación (contraseña/huella) y los mata automáticamente.
- En Windows, se detecta la falta de privilegios de administrador y se advierte al usuario.
- Los comandos ejecutados se desduplican por hash para evitar re-ejecuciones accidentales.

## Características

- Sin dependencias externas de Python (solo `http.server`, `subprocess`, `pty`)
- Panel de control flotante con indicador de conexión en tiempo real
- Detección automática de navegación SPA (cambios de chat)
- Auto-inicio/parada según el prompt del agente esté presente
- Cola de comandos FIFO con ejecución secuencial
- Timeout de 25s por comando con reinicio automático del shell

## Licencia

Este proyecto es de uso libre. Consulta el archivo `LICENSE` si está presente.
