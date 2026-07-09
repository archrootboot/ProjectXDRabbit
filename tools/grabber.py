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
            if 'emulator' in line and 'device' in line:
                id_only = line.split('\t')[0].strip()
                emulators.append([id_only, port])
                port += 1

        if not emulators:
            logger.log("⚠ No emulators detected via ADB.")
        else:
            logger.log(f"✓ Found {len(emulators)} emulator(s): {[e[0] for e in emulators]}")

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
