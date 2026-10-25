#!/usr/bin/env ruby
require 'openssl'
require 'base64'
require 'json'
require 'open3'
require 'tmpdir'

temporary = Dir.mktmpdir('mastodon-launch-')
at_exit { FileUtils.rm_rf(temporary) }
upload_directory = File.join(temporary, 'uploads')

launcher = File.expand_path('../../clusters/homelab/apps/mastodon/launch.rb', __dir__)
key = OpenSSL::PKey::EC.generate('prime256v1')
runner = <<~RUBY
  require 'json'
  require 'fileutils'
  require 'tempfile'
  FileUtils.define_singleton_method(:rm_f) { |path| ($removed ||= []) << path }
  class File
    class << self
      alias_method :original_read, :read
      def read(path, *args)
        return ARGV.shift if path == '/run/mastodon/vapid.pem'
        return ARGV.shift if path == '/opt/mastodon/.env.production'
        return 'fixture#=$literal' if path == '/run/mastodon/smtp-password'
        original_read(path, *args)
      end
    end
  end
  def exec(*args)
    Tempfile.create('upload') do |file|
      puts JSON.generate({private: ENV.fetch('VAPID_PRIVATE_KEY'), public: ENV.fetch('VAPID_PUBLIC_KEY'), command: args, removed: ($removed || []), smtp: ENV.fetch('SMTP_PASSWORD'), upload_directory: File.dirname(file.path), upload_mode: File.stat(File.dirname(file.path)).mode & 0777})
    end
  end
  eval(File.read(#{launcher.inspect}).gsub('/tmp/mastodon', #{upload_directory.inspect}), TOPLEVEL_BINDING, #{launcher.inspect})
RUBY
stdout, stderr, result = Open3.capture3('ruby', '-e', runner, '--', key.to_pem, 'LOCAL_DOMAIN=chosen.example', 'bundle', 'exec', 'puma')
raise 'launcher failed for a valid key' unless result.success?
data = JSON.parse(stdout)
raise 'upload tempfile escaped the private directory' unless data.fetch('upload_directory') == upload_directory
raise 'upload directory is accessible to other users' unless data.fetch('upload_mode') == 0700
raise 'wrong command' unless data.fetch('command') == ['bundle', 'exec', 'puma']
raise 'web launcher cleared worker readiness' unless data.fetch('removed').empty?
raise 'SMTP password changed' unless data.fetch('smtp') == 'fixture#=$literal'
raise 'wrong private scalar' unless Base64.urlsafe_decode64(data.fetch('private')) == key.private_key.to_s(2).rjust(32, "\0")
raise 'wrong public point' unless Base64.urlsafe_decode64(data.fetch('public')) == key.public_key.to_octet_string(:uncompressed)
raise 'keys contain padding' if [data.fetch('private'), data.fetch('public')].any? { |value| value.include?('=') }
[
  [key.to_pem, 'LOCAL_DOMAIN=REPLACE_ME', 'placeholders'],
  [OpenSSL::PKey::EC.generate('secp384r1').to_pem, 'LOCAL_DOMAIN=chosen.example', 'P-256'],
  [key.public_to_pem, 'LOCAL_DOMAIN=chosen.example', 'private P-256']
].each do |pem, config, message|
  stdout, stderr, result = Open3.capture3('ruby', '-e', runner, '--', pem, config, 'bundle', 'exec', 'puma')
  raise 'invalid input launched application' if result.success? || !stdout.empty?
  raise 'wrong failure' unless stderr.include?(message)
end
stdout, _, result = Open3.capture3('ruby', '-e', runner, '--', key.to_pem, 'LOCAL_DOMAIN=chosen.example', 'bundle', 'exec', 'sidekiq', '-c', '5')
raise 'worker launch failed' unless result.success?
data = JSON.parse(stdout)
raise 'stale readiness survived restart' unless data.fetch('removed') == ['/opt/mastodon/tmp/sidekiq_process_has_started_and_will_begin_processing_jobs']
raise 'worker command changed' unless data.fetch('command') == ['bundle', 'exec', 'sidekiq', '-c', '5']
for password in ['', 'REPLACE_ME']
  invalid_runner = runner.sub("return 'fixture#=$literal'", "return #{password.inspect}")
  stdout, stderr, result = Open3.capture3('ruby', '-e', invalid_runner, '--', key.to_pem, 'LOCAL_DOMAIN=chosen.example', 'bundle', 'exec', 'puma')
  raise 'invalid SMTP credential launched app' if result.success? || !stdout.empty?
  raise 'wrong SMTP rejection' unless stderr.include?('SMTP password is missing or still a placeholder')
end
puts 'Mastodon launcher: VAPID, exact SMTP password, placeholder rejection, forwarding, and restart readiness passed'
