from pathlib import Path


def remove_file_extension(file_path: str) -> str:
    """
    Returns the file path without its extension.

    Args:
        file_path (str or Path): The file path.

    Returns:
        Path: The file path without the extension.
    """
    file_path = Path(file_path)
    return str(file_path.with_suffix(""))


def add_file_extension(file_path: str, extension: str) -> str:
    """
    Adds a file extension to the given file path if it doesn't already have one.

    Args:
        file_path (str or Path): The file path.
        extension (str): The extension to add (e.g., ".txt", ".json").

    Returns:
        Path: The file path with the added extension.
    """

    file_path = Path(file_path)

    if not extension.startswith("."):
        extension = f".{extension}"

    if file_path.suffix != extension:
        return str(file_path.with_suffix(extension))

    return str(file_path)


def get_associated_json(usd_path: str) -> str:
    usd_path = remove_file_extension(usd_path)
    json_path = add_file_extension(usd_path, "json")
    return json_path


def save_ascii_to_file(file_path: str, ascii_str: str) -> bool:
    """
    Saves ASCII data to a file, creating directories if necessary.

    Args:
        json_data (bytes): The JSON data encoded in ASCII.
        file_path (str or Path): The path to the file where the data will be saved.

    Returns:
        True if succesfull.
    """
    try:

        file_path: Path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(data=str(ascii_str), encoding="ascii")
        print(f"Data successfully saved to {file_path}")
        return True
    except IOError as e:
        print(IOError(f"An error occurred while writing to the file: {e}"))
        return False
