function vplay --description "Modular playlist-based video player with mpv control"
    set -l source_file (status --current-filename)
    set -l app_dir (realpath (dirname "$source_file")/..)
    set -l venv_dir "$app_dir/.venv"
    set -l python "$venv_dir/bin/python"

    if not test -x "$python"
        echo "Setting up vplay virtual environment..."
        python3 -m venv "$venv_dir"
        "$python" -m pip install --quiet --upgrade pip
        "$python" -m pip install --quiet -e "$app_dir"
    end

    pushd "$app_dir" >/dev/null

    if not "$python" -c "import vplay.app" >/dev/null 2>&1
        "$python" -m pip install --quiet -e "$app_dir"
    end

    "$python" -m vplay $argv
    set -l exit_code $status
    popd >/dev/null
    return $exit_code
end
