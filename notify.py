"""Entrega novedades pendientes; conserva las que fallen para el próximo escaneo."""
import hashlib
import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

OUTPUT = Path('site/data.json')


def save(state):
    temporary = OUTPUT.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(OUTPUT)


def run():
    state = json.loads(OUTPUT.read_text(encoding='utf-8'))
    pending = state.setdefault('pending_notifications', {})
    if not pending:
        print('Sin novedades pendientes de correo.')
        return
    required = ['SMTP_USERNAME', 'SMTP_PASSWORD', 'MAIL_TO']
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError('Configurar secretos/variables: ' + ', '.join(missing))
    recipients = list(dict.fromkeys(a.strip() for a in os.environ['MAIL_TO'].split(',') if a.strip()))
    sender = os.environ['SMTP_USERNAME']
    failures = []
    with smtplib.SMTP(os.environ.get('SMTP_HOST', 'smtp.gmail.com'), int(os.environ.get('SMTP_PORT', '587')), timeout=45) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(sender, os.environ['SMTP_PASSWORD'])
        for recipient in recipients:
            token = hashlib.sha256(recipient.lower().encode()).hexdigest()
            waiting = [event for event in pending.values() if token not in event.get('delivered', [])]
            for start in range(0, len(waiting), 100):
                batch = waiting[start:start + 100]
                message = EmailMessage()
                message['From'] = sender
                message['To'] = recipient
                message['Subject'] = f'JW.org: {len(batch)} novedades detectadas'
                body = ['Novedades y actualizaciones detectadas en jw.org (español).', '']
                for event in batch:
                    body.extend([f"{event['kind']}: {event['title']}", event['url'], f"Detectado: {event['detected']}", ''])
                body.append('Se avisa al completar el escaneo programado; la carga inicial no genera correos.')
                if state.get('successful_sources', 0) < state.get('total_sources', 0):
                    body.append('La revisión quedó incompleta: alguna fuente falló. Consultá el panel.')
                message.set_content('\n'.join(body))
                try:
                    refused = smtp.send_message(message)
                    if refused:
                        raise RuntimeError('El servidor rechazó el destinatario')
                except Exception:
                    failures.append('No se pudo entregar un lote; queda pendiente para reintento.')
                    break
                for event in batch:
                    event.setdefault('delivered', []).append(token)
                save(state)
    tokens = {hashlib.sha256(a.lower().encode()).hexdigest() for a in recipients}
    state['pending_notifications'] = {key: event for key, event in pending.items() if not tokens.issubset(set(event.get('delivered', [])))}
    save(state)
    if failures:
        raise RuntimeError(' '.join(failures))
    print('Correos entregados al servidor SMTP.')


if __name__ == '__main__':
    run()
