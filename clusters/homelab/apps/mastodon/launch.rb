require 'openssl'
require 'base64'
require 'fileutils'

# Mastodon expects raw P-256 Web Push keys; SSM retains the generated PEM key.
key = OpenSSL::PKey.read(File.read('/run/mastodon/vapid.pem'))
abort 'VAPID key must be a private P-256 key' unless key.private? && key.group.curve_name == 'prime256v1'
ENV['VAPID_PRIVATE_KEY'] = Base64.urlsafe_encode64(key.private_key.to_s(2).rjust(32, "\0"), padding: false)
ENV['VAPID_PUBLIC_KEY'] = Base64.urlsafe_encode64(key.public_key.to_octet_string(:uncompressed), padding: false)
abort 'Mastodon configuration still contains placeholders' if File.read('/opt/mastodon/.env.production').include?('REPLACE_ME')
if ARGV[0, 3] == %w[bundle exec sidekiq]
  FileUtils.rm_f('/opt/mastodon/tmp/sidekiq_process_has_started_and_will_begin_processing_jobs')
end
exec(*ARGV)
