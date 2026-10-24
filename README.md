# Correos de novedades

Destinatarios: emilio.antunez.88@gmail.com y laotracaradelatorre@gmail.com.
El escaneo actual se ejecuta cada 6 horas. Los correos se envían cuando termina y hay novedades: publicaciones nuevas, incluidos vídeos, Broadcasting, canciones, libros, folletos y tarjetas que aparezcan en las fuentes consultadas. Los cambios de fecha, título o contenido de publicaciones ya conocidas no generan correos. Los avisos de actualizaciones pendientes de versiones anteriores se descartan. La carga inicial de cada fuente no genera correos.

## Activación

En https://github.com/emilioantunez/laotracarascanner/settings/secrets/actions crear estos secretos de repositorio:

- `SMTP_USERNAME`: dirección completa de la cuenta Gmail que enviará los correos.
- `SMTP_PASSWORD`: contraseña de aplicación de esa cuenta, no su contraseña habitual.

Crear la contraseña de aplicación en https://myaccount.google.com/apppasswords (requiere verificación en dos pasos y disponibilidad de esta función en la cuenta). No colocar contraseñas en el código ni en el chat.

Configuración predeterminada: smtp.gmail.com, puerto 587, STARTTLS. Referencia de Google: https://support.google.com/mail/answer/7104828

Una vez creados los secretos, ejecutar el workflow desde Actions > Revisar JW y publicar panel > Run workflow. Si todavía no hay novedades pendientes, no envía correo.

Las notificaciones pendientes se guardan en el historial. Cada destinatario se confirma por separado y los fallos se reintentan en la próxima ejecución. Si el correo falla, el workflow conserva el historial y publica el panel, pero termina con error para que el fallo sea visible en Actions. La aceptación del servidor SMTP no garantiza la llegada a la bandeja principal; revisar spam. Una interrupción entre el envío y el guardado puede ocasionar un aviso duplicado.
