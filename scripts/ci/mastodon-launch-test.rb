#!/usr/bin/env ruby
require 'openssl'
require 'base64'
require 'json'
require 'open3'

launcher = File.expand_path('../../clusters/homelab/apps/mastodon/launch.rb', __dir__)
key = OpenSSL::PKey::EC.generate('prime256v1')
runner = <<~RUBY
  require 'json'
  require 'fileutils'
  FileUtils.define_singleton_method(:rm_f) { |path| ($removed ||= []) << path }
  class File
    class << self
      alias_method :original_read, :read
      def read(path, *args)
        return ARGV.shift if path == '/run/mastodon/vapid.pem'
        return ARGV.shift if path == '/opt/mastodon/.env.production'
        original_read(path, *args)
      end
    end
  end
  def exec(*args)
    puts JSON.generate({private: ENV.fetch('VAPID_PRIVATE_KEY'), public: ENV.fetch('VAPID_PUBLIC_KEY'), command: args, removed: ($removed || [])})
  end
  load #{launcher.inspect}
RUBY
stdout, stderr, result = Open3.capture3('ruby', '-e', runner, '--', key.to_pem, 'LOCAL_DOMAIN=chosen.example', 'bundle', 'exec', 'puma')
raise 'launcher failed for a valid key' unless result.success?
data = JSON.parse(stdout)
raise 'wrong command' unless data.fetch('command') == ['bundle', 'exec', 'puma']
raise 'web launcher cleared worker readiness' unless data.fetch('removed').empty?
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
puts 'Mastodon launcher: VAPID conversion, config rejection, command forwarding, and stale readiness cleanup passed'
