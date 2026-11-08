from pathlib import Path
from datetime import datetime
import hashlib
import json
import logging
import shutil
import subprocess
import tempfile
import re

MAX_BACKUPS = 3

JOGO = Path(r"C:\Program Files (x86)\KONAMI\Pro Evolution Soccer 2013\pes2013.exe")
SAVE_LOCAL = Path(r"C:\Users\warap\Documents\KONAMI\Pro Evolution Soccer 2013\save")
NUVEM = "backup_nuvem:PES2013_Sync/save"
BACKUP_NUVEM = "backup_nuvem:PES2013_Sync/backups"

PASTA_SCRIPT = Path(__file__).resolve().parent
ESTADO = PASTA_SCRIPT / "estado_sync.json"
BACKUPS = PASTA_SCRIPT / "backups"
LOG = PASTA_SCRIPT / "pes_sync.log"

logging.basicConfig(
    filename=LOG,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    encoding="utf-8",
)


def rclone(*args):
    # Nao registra credenciais ou tokens no arquivo de log.
    resultado = subprocess.run(["rclone", *args], capture_output=True, text=True)
    if resultado.returncode != 0:
        raise RuntimeError(
            "Erro do Rclone: " + (resultado.stderr.strip() or f"codigo {resultado.returncode}")
        )
    return resultado


def inventario(pasta):
    resultado = {}
    if not pasta.exists():
        return resultado
    for arquivo in pasta.rglob("*"):
        if not arquivo.is_file():
            continue
        hash_arquivo = hashlib.sha256()
        with arquivo.open("rb") as f:
            for bloco in iter(lambda: f.read(1024 * 1024), b""):
                hash_arquivo.update(bloco)
        resultado[arquivo.relative_to(pasta).as_posix()] = hash_arquivo.hexdigest()
    return resultado


def carregar_estado():
    if not ESTADO.exists():
        return None
    return json.loads(ESTADO.read_text(encoding="utf-8"))


def salvar_estado(dados):
    temporario = ESTADO.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, indent=2), encoding="utf-8")
    temporario.replace(ESTADO)


def baixar_temporario(destino):
    # Falha se a pasta remota nao existe ou se nao houver acesso.
    rclone("lsf", NUVEM)
    rclone("copy", NUVEM, str(destino))


def fazer_backup():
    if not SAVE_LOCAL.is_dir():
        return
    data = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destino = BACKUPS / data
    shutil.copytree(SAVE_LOCAL, destino)
    logging.info("Backup local criado: %s", destino)



def preparar_saves(nuvem_local):
    local = inventario(SAVE_LOCAL)
    remoto = inventario(nuvem_local)
    anterior = carregar_estado()

    # Primeira execucao
    if anterior is None:
        if local != remoto:
            raise RuntimeError(
                "Primeira execucao: saves diferentes. "
                "Configure a sincronizacao inicial."
            )

        salvar_estado(local)
        print("Estado inicial registrado.")
        logging.info("Estado inicial registrado.")
        return

    # Nenhuma diferenca entre computador e nuvem
    if local == remoto:
        salvar_estado(local)
        print("Saves ja estao atualizados.")
        logging.info(
            "Saves locais e remotos iguais (%d arquivos)",
            len(local)
        )
        return

    # Alteracoes locais feitas fora da automacao
    if local != anterior:
        print("Alteracoes locais detectadas.")
        logging.info(
            "Alteracoes locais detectadas fora da automacao."
        )

        if remoto != anterior:
            logging.warning(
                "Alteracoes em ambos os computadores. "
                "Priorizando a versao local."
            )

        # Preservar os saves antes do envio
        fazer_backup()

        # Preservar a versao atual da nuvem
        data = datetime.now().strftime(
            "%Y%m%d_%H%M%S_%f"
        )

        backup_remoto = f"{BACKUP_NUVEM}/{data}"

        print("Criando backup da nuvem...")
        rclone("copy", NUVEM, backup_remoto)

        print("Enviando alteracoes locais...")
        rclone("sync", str(SAVE_LOCAL), NUVEM)

        # Confirmar que o upload ficou correto
        with tempfile.TemporaryDirectory() as temp:
            verificacao = Path(temp)
            baixar_temporario(verificacao)

            if inventario(verificacao) != local:
                raise RuntimeError(
                    "Falha ao verificar o upload."
                )

        salvar_estado(local)

        print("Alteracoes locais sincronizadas!")
        logging.info(
            "Upload local confirmado (%d arquivos)",
            len(local)
        )
        return

    # Somente a nuvem foi modificada
    print("Baixando saves atualizados...")
    fazer_backup()

    rclone("sync", str(nuvem_local), str(SAVE_LOCAL))

    if inventario(SAVE_LOCAL) != remoto:
        raise RuntimeError(
            "Falha ao verificar os arquivos baixados."
        )

    salvar_estado(remoto)

    print("Download concluido.")
    logging.info(
        "Download concluido (%d arquivos)",
        len(remoto)
    )



def iniciar_jogo():
    if not JOGO.is_file():
        raise FileNotFoundError(f"Executavel nao encontrado: {JOGO}")
    print("Iniciando PES 2013...")
    logging.info("Abrindo PES 2013")
    processo = subprocess.Popen([str(JOGO)], cwd=str(JOGO.parent))
    processo.wait()
    print("PES 2013 foi fechado.")
    logging.info("PES 2013 encerrado (codigo: %s)", processo.returncode)


def enviar_saves(referencia):
    atual = inventario(SAVE_LOCAL)
    with tempfile.TemporaryDirectory() as temp:
        remoto = Path(temp)
        baixar_temporario(remoto)
        if inventario(remoto) != referencia:
            raise RuntimeError("A nuvem mudou durante a partida. Upload bloqueado para evitar conflitos.")

    if atual == referencia:
        print("Nenhuma alteracao para enviar.")
        logging.info("Nenhuma alteracao para enviar")
        return

    fazer_backup()
    data = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    print("Enviando saves...")
    rclone("sync", str(SAVE_LOCAL), NUVEM, "--backup-dir", f"{BACKUP_NUVEM}/{data}")

    with tempfile.TemporaryDirectory() as temp:
        remoto = Path(temp)
        baixar_temporario(remoto)
        if inventario(remoto) != atual:
            raise RuntimeError("Upload enviado, mas nao passou na verificacao. Confira os arquivos antes de jogar.")

    salvar_estado(atual)
    print("Sincronizacao concluida com sucesso!")
    logging.info("Upload confirmado (%d arquivos)", len(atual))

def backup_automatico(nome):
    return re.fullmatch(
        r"\d{8}_\d{6}_\d{6}", nome
    ) is not None


def limpar_backups_locais():
    if not BACKUPS.exists():
        return

    pastas = sorted(
        (
            p for p in BACKUPS.iterdir()
            if p.is_dir() and backup_automatico(p.name)
        ),
        key=lambda p: p.name,
        reverse=True
    )

    for pasta in pastas[MAX_BACKUPS:]:
        shutil.rmtree(pasta)
        logging.info(
            "Backup antigo removido: %s", pasta
        )


def limpar_backups_nuvem():
    resultado = rclone(
        "lsf",
        BACKUP_NUVEM,
        "--dirs-only"
    )

    pastas = sorted(
        (
            nome.rstrip("/")
            for nome in resultado.stdout.splitlines()
            if backup_automatico(nome.rstrip("/"))
        ),
        reverse=True
    )

    for pasta in pastas[MAX_BACKUPS:]:
        rclone(
            "purge",
            f"{BACKUP_NUVEM}/{pasta}"
        )
        logging.info(
            "Backup remoto antigo removido: %s",
            pasta
        )


def main():
    logging.info("=== Inicio da execucao ===")
    try:
        if not SAVE_LOCAL.is_dir():
            raise FileNotFoundError(f"Pasta de saves nao encontrada: {SAVE_LOCAL}")
        with tempfile.TemporaryDirectory() as temp:
            remoto = Path(temp)
            baixar_temporario(remoto)
            preparar_saves(remoto)

        referencia = inventario(SAVE_LOCAL)
        iniciar_jogo()
        enviar_saves(referencia)
        try:
            limpar_backups_locais()
            limpar_backups_nuvem()
        except Exception:
            logging.exception(
                "Falha na limpeza de backups antigos"
            )
        logging.info("=== Execucao concluida sem erros ===")
        return 0
    except Exception as erro:
        logging.exception("Falha na automacao")
        print(f"\nERRO: {erro}")
        print(f"Detalhes registrados em: {LOG}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
