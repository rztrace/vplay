class Vplay < Formula
  desc "Advanced macOS CLI video player with a TUI interface"
  homepage "https://github.com/rztrace/vplay"
  version "1.1-beta"
  license :cannot_represent

  on_macos do
    if Hardware::CPU.arm?
      url "https://github.com/rztrace/vplay/releases/download/v1.1-beta/vplay-macos-arm64.tar.gz"
      sha256 "d52fa722652c0668ac68556bc7dc9f41eb009ed7f4ce5fe169996f89d02954a5"
    else
      odie "vplay currently provides a precompiled macOS binary for Apple Silicon."
    end
  end

  depends_on "mpv"
  depends_on "yt-dlp"

  def install
    libexec.install "vplay"
    (bin/"vplay").write <<~EOS
      #!/bin/bash
      export VPLAY_INSTALL_METHOD=homebrew
      exec "#{libexec}/vplay" "$@"
    EOS
    chmod 0755, bin/"vplay"
  end

  test do
    assert_match "vplay 1.1 beta", shell_output("#{bin}/vplay --version")
  end
end
