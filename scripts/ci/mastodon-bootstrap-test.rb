#!/usr/bin/env ruby
require 'open3'
require 'json'

script = File.expand_path('../../clusters/homelab/apps/mastodon/bootstrap.rb', __dir__)
runner = <<~RUBY
  require 'ostruct'
  require 'json'
  $mode = ARGV.shift
  $events = []
  class File
    def self.read(path)
      raise 'Unexpected file read' unless path == '/run/mastodon/admin-password'
      $events << 'password-read'
      return 'short' if $mode == 'invalid-password'
      'p' * 40
    end
  end
  class Account
    def self.find_local(username)
      raise 'Wrong username' unless username == 'rodman'
      return nil unless %w[existing foreign regular unconfirmed unapproved].include?($mode)
      user = OpenStruct.new(email: $mode == 'foreign' ? 'someone@example.test' : 'rodman@stuhlmuller.net',
                            role: OpenStruct.new(name: $mode == 'regular' ? 'User' : 'Owner'))
      def user.confirmed?; $mode != 'unconfirmed'; end
      def user.approved?; $mode != 'unapproved'; end
      OpenStruct.new(user: user)
    end
    def initialize(username:)
      raise 'Wrong new username' unless username == 'rodman'
    end
  end
  class UserRole
    def self.find_by(name:)
      raise 'Wrong role' unless name == 'Owner'
      $mode == 'missing-role' ? nil : OpenStruct.new(id: 1)
    end
  end
  class User
    attr_accessor :account, :confirmed_at
    def self.transaction; yield; end
    def initialize(**attributes)
      raise 'Incorrect owner attributes' unless attributes[:email] == 'rodman@stuhlmuller.net' &&
        attributes[:password] == 'p' * 40 && attributes[:role_id] == 1 &&
        attributes[:agreement] && attributes[:bypass_registration_checks] && attributes[:confirmed_at].is_a?(Time)
    end
    def save!
      raise('p' * 40) if $mode == 'save-error'
      $events << 'saved'
    end
    def mark_email_as_confirmed!; $events << 'confirmed'; end
    def approve!; $events << 'approved'; end
  end
  load #{script.inspect}
  puts JSON.generate(events: $events)
RUBY
for mode in %w[fresh existing]
  stdout, stderr, result = Open3.capture3('ruby', '-e', runner, '--', mode)
  raise stderr unless result.success?
  events = JSON.parse(stdout.lines.last).fetch('events')
  expected = mode == 'fresh' ? %w[password-read saved confirmed approved] : []
  raise 'Incorrect bootstrap lifecycle' unless events == expected
  raise 'Password printed' if (stdout + stderr).include?('p' * 40)
end
for mode in %w[foreign regular unconfirmed unapproved invalid-password missing-role save-error]
  stdout, stderr, result = Open3.capture3('ruby', '-e', runner, '--', mode)
  raise 'Unsafe bootstrap accepted' if result.success?
  raise 'Password printed on failure' if (stdout + stderr).include?('p' * 40)
end
puts 'Mastodon bootstrap: first creation, no repeat writes, ownership refusal, and private errors passed'
