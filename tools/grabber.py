import subprocess
import logger


def get_emulator_list():
    try:
        result = subprocess.run(
            ['adb', 'devices'],
            capture_output=True,
            text=True,
            check=True
        )

        lines = result.stdout.strip().split('\n')[1:]

        emulators = []
        port = 8200
        for line in lines:
            line = line.strip()
            if not line or 'offline' in line or 'unauthorized' in line:
                continue
            # Accept both emulator-XXXX  and  <host>:<port>  style devices
            if 'device' in line:
                id_only = line.split()[0].strip()
                is_emulator = 'emulator' in id_only
                is_tcpip    = ':' in id_only          # e.g. 127.0.0.1:21503
                if is_emulator or is_tcpip:
                    emulators.append([id_only, port])
                    port += 1

        if not emulators:
            logger.log("⚠ No devices detected via ADB.")
        else:
            logger.log(f"✓ Found {len(emulators)} device(s): {[e[0] for e in emulators]}")

        return emulators

    except FileNotFoundError:
        logger.log("✗ ADB not found. Is Android SDK installed and added to PATH?")
        return []
    except subprocess.CalledProcessError as e:
        logger.log(f"✗ ADB command failed: {e}")
        return []
    except Exception as e:
        logger.log(f"✗ Unexpected error in get_emulator_list: {e}")
        return []
