class Vplay < Formula
  desc "Advanced macOS CLI video player with a TUI interface"
  homepage "https://github.com/rztrace/vplay"
  version "1.1-beta.4"
  license :cannot_represent

  on_macos do
    if Hardware::CPU.arm?
      url "https://github.com/rztrace/vplay/releases/download/v1.1-beta.4/vplay-macos-arm64.tar.gz"
      sha256 "c694afd68826c981b98360d416eeb541e0f377d318feab771d664cd04e37e0e5"
    else
      odie "vplay currently provides a precompiled macOS binary for Apple Silicon."
    end
  end

  depends_on "mpv"
  depends_on "yt-dlp"

  def install
    libexec.install "vplay", "_internal"
    (bin/"vplay").write <<~EOS
      #!/bin/bash
      export VPLAY_INSTALL_METHOD=homebrew
      exec "#{libexec}/vplay" "$@"
    EOS
    chmod 0755, bin/"vplay"
  end

  test do
    assert_match "vplay 1.1 beta 4", shell_output("#{bin}/vplay --version")
  end
end
